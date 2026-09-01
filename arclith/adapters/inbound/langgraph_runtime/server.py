from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from arclith.adapters.inbound.langgraph_runtime.api import (
    create_langgraph_runtime_app,
)
from arclith.adapters.inbound.langgraph_runtime.catalog import (
    PostgresRuntimeCatalog,
)
from arclith.adapters.inbound.langgraph_runtime.coordination import (
    RedisRunCoordinator,
)
from arclith.adapters.inbound.langgraph_runtime.loader import load_graphs
from arclith.adapters.inbound.langgraph_runtime.runtime import LangGraphRuntime
from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.domain.ports.outbound.observability import ObservabilityRuntimePort
from arclith.infrastructure.langgraph_bootstrap import (
    LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR,
)


def create_durable_langgraph_runtime_app(
    config_path: str | Path = "langgraph.json",
    *,
    database_uri: str | None = None,
    redis_uri: str | None = None,
    redis_prefix: str | None = None,
    run_timeout_seconds: int | None = None,
    observability_runtime: ObservabilityRuntimePort | None = None,
) -> FastAPI:
    resolved_database_uri = _required_uri(
        database_uri,
        primary_env="DATABASE_URI",
        fallback_env="POSTGRESQL_URL",
    )
    resolved_redis_uri = _required_uri(
        redis_uri,
        primary_env="REDIS_URI",
        fallback_env="REDIS_URL",
    )
    graphs = load_graphs(config_path)
    resolved_observability = (
        observability_runtime
        if observability_runtime is not None
        else _graph_observability_runtime(graphs.values())
    )

    pool, catalog = _postgres_catalog(resolved_database_uri)
    redis_client = _redis_client(resolved_redis_uri)
    coordinator = RedisRunCoordinator(
        redis_client,
        prefix=redis_prefix
        or os.getenv("ARCLITH_LANGGRAPH_REDIS_PREFIX")
        or "arclith:langgraph",
        lease_seconds=_positive_int_env(
            "ARCLITH_LANGGRAPH_REDIS_LEASE_SECONDS",
            30,
        ),
    )
    runtime = LangGraphRuntime(
        graphs,
        catalog,
        coordinator,
        run_timeout_seconds=run_timeout_seconds
        or _positive_int_env("ARCLITH_LANGGRAPH_RUN_TIMEOUT_SECONDS", 900),
        observability_runtime=resolved_observability,
    )
    app = create_langgraph_runtime_app(runtime)
    resolved_observability.instrument_fastapi(app)
    auto_setup = _boolean_env("ARCLITH_LANGGRAPH_AUTO_SETUP", True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        resolved_observability.start()
        try:
            await pool.open()
            saver, store = await _build_langgraph_persistence(
                pool,
                setup=auto_setup,
            )
            _attach_persistence(graphs.values(), saver=saver, store=store)
            if auto_setup:
                await runtime.setup()
            if not await coordinator.healthcheck():
                raise RuntimeError("Redis coordination is unavailable")
            yield
        finally:
            try:
                await coordinator.close()
            finally:
                try:
                    await pool.close()
                finally:
                    try:
                        resolved_observability.force_flush()
                    finally:
                        resolved_observability.shutdown()

    app.router.lifespan_context = lifespan
    return app


def _graph_observability_runtime(graphs: Any) -> ObservabilityRuntimePort:
    runtimes: dict[int, ObservabilityRuntimePort] = {}
    for graph in graphs:
        candidate = getattr(graph, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, None)
        if candidate is None:
            continue
        if not isinstance(candidate, ObservabilityRuntimePort):
            raise TypeError("Le runtime d'observabilite attache au graphe est invalide")
        runtimes[id(candidate)] = candidate
    if not runtimes:
        return NoOpObservabilityRuntime()
    if len(runtimes) > 1:
        raise RuntimeError(
            "Tous les graphes du runtime durable doivent partager la meme instance "
            "Arclith ou fournir observability_runtime explicitement"
        )
    return next(iter(runtimes.values()))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Arclith durable open source LangGraph runtime",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("ARCLITH_LANGGRAPH_CONFIG", "langgraph.json"),
    )
    parser.add_argument(
        "--host",
        default=os.getenv("LANGGRAPH_HOST", "0.0.0.0"),  # nosec B104  # noqa: S104
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_positive_int_env("LANGGRAPH_PORT", 2024),
    )
    parser.add_argument(
        "--graceful-timeout",
        type=int,
        default=_positive_int_env("ARCLITH_GRACEFUL_TIMEOUT_SECONDS", 120),
    )
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        create_durable_langgraph_runtime_app(args.config),
        host=args.host,
        port=args.port,
        timeout_graceful_shutdown=args.graceful_timeout,
        access_log=os.getenv("ARCLITH_ACCESS_LOG", "false").lower() == "true",
    )


async def _build_langgraph_persistence(
    pool: Any,
    *,
    setup: bool,
) -> tuple[Any, Any]:
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
    except ImportError as error:
        raise RuntimeError(
            "Le runtime durable exige arclith[langgraph-runtime]"
        ) from error

    saver = AsyncPostgresSaver(pool)
    store = AsyncPostgresStore(pool)
    if setup:
        await saver.setup()
        await store.setup()
    return saver, store


def _attach_persistence(graphs: Any, *, saver: Any, store: Any) -> None:
    for graph in graphs:
        graph.checkpointer = saver
        graph.store = store


def _postgres_catalog(database_uri: str) -> tuple[Any, PostgresRuntimeCatalog]:
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError as error:
        raise RuntimeError(
            "Le runtime durable exige arclith[langgraph-runtime]"
        ) from error

    pool = AsyncConnectionPool(
        conninfo=database_uri,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        min_size=1,
        max_size=_positive_int_env("ARCLITH_LANGGRAPH_POSTGRES_POOL_SIZE", 10),
        open=False,
    )
    return pool, PostgresRuntimeCatalog(pool)


def _redis_client(redis_uri: str) -> Any:
    try:
        from redis.asyncio import Redis
    except ImportError as error:
        raise RuntimeError(
            "Le runtime durable exige arclith[langgraph-runtime]"
        ) from error
    return Redis.from_url(
        redis_uri,
        decode_responses=True,
        health_check_interval=30,
    )


def _required_uri(
    configured: str | None,
    *,
    primary_env: str,
    fallback_env: str,
) -> str:
    value = configured or os.getenv(primary_env) or os.getenv(fallback_env)
    if not value:
        raise RuntimeError(
            f"Variable {primary_env} ou {fallback_env} requise pour le runtime durable"
        )
    return _normalize_postgresql_scheme(value)


def _normalize_postgresql_scheme(uri: str) -> str:
    for scheme in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if uri.startswith(scheme):
            return f"postgresql://{uri.removeprefix(scheme)}"
    return uri


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} doit etre strictement positif")
    return value


def _boolean_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} doit etre un booleen")


if __name__ == "__main__":  # pragma: no cover - console entrypoint
    main()
