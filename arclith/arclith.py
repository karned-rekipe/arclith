from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

from arclith.adapters.outbound.relational.registry import RelationalMapperRegistry
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.domain.ports.outbound.embedding import EmbeddingPort
from arclith.domain.ports.outbound.file_storage import FileStoragePort
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.domain.ports.outbound.observability import (
    CorrelationContextPort,
    MetricPort,
    ObservabilityRuntimePort,
    TraceAnonymizer,
    TracePort,
)
from arclith.domain.ports.outbound.repository import Repository
from arclith.domain.ports.outbound.vector_store import VectorStorePort
from arclith.infrastructure.config import (
    AppConfig,
    LangGraphStreamMode,
    load_config_dir,
    load_config_file,
)
from arclith.infrastructure.channel_factory import ChannelSenderRegistry
from arclith.infrastructure.embedding_factory import EmbeddingRegistry
from arclith.infrastructure.file_storage_factory import FileStorageRegistry
from arclith.infrastructure.langgraph_bootstrap import (
    LANGGRAPH_UNSET as _LANGGRAPH_UNSET,
)
from arclith.infrastructure.repository_factory import RepositoryRegistry
from arclith.infrastructure.vector_store_factory import VectorStoreRegistry

if TYPE_CHECKING:
    import fastmcp as _fastmcp
    from fastapi import FastAPI

    from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus
    from arclith.application.command_bus import CommandDispatcher
    from arclith.infrastructure.langgraph_persistence_factory import (
        LangGraphPersistenceRegistry,
    )

T = TypeVar("T", bound=Entity)
R = TypeVar("R", bound=Repository[Any])
_UVICORN_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {},
    "loggers": {
        "uvicorn": {"handlers": [], "propagate": False},
        "uvicorn.access": {"handlers": [], "propagate": False},
        "uvicorn.error": {"handlers": [], "propagate": False},
    },
}
_LEVEL_MAP: dict[str, LogLevel] = {
    "DEBUG": LogLevel.DEBUG,
    "INFO": LogLevel.INFO,
    "WARNING": LogLevel.WARNING,
    "ERROR": LogLevel.ERROR,
    "CRITICAL": LogLevel.CRITICAL,
}


class _UvicornLogInterceptHandler(logging.Handler):
    def __init__(
        self,
        logger: Logger,
        correlation: CorrelationContextPort | None = None,
    ) -> None:
        super().__init__()
        self._logger = logger
        self._correlation = correlation

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.exc_info:
            exc = record.exc_info[1]
            tb = "".join(traceback.format_exception(exc))
            message = f"{message}\n{tb}"
        injected: Mapping[str, str | bool] = {}
        if self._correlation is not None:
            injected = self._correlation.from_log_record(record)
            if not injected:
                injected = self._correlation.current()
        self._logger.log(
            _LEVEL_MAP.get(record.levelname, LogLevel.INFO),
            message,
            **injected,
        )


class Arclith:
    def __init__(
        self,
        config_path: str | Path,
        *,
        trace_anonymizer: TraceAnonymizer | None = None,
        opentelemetry_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        p = Path(config_path)
        if p.is_dir():
            self.config: AppConfig = load_config_dir(p)
        elif p.is_file():
            self.config = load_config_file(p)
        else:
            raise ValueError(f"Config path not found: {p}")
        self._trace_anonymizer = trace_anonymizer
        self._opentelemetry_overrides = dict(opentelemetry_overrides or {})

    @cached_property
    def logger(self) -> Logger:
        from arclith.adapters.outbound.console.logger import ConsoleLogger

        if self.config.adapters.logger == "console":
            return ConsoleLogger()

        raise ValueError(
            f"logger={self.config.adapters.logger} non supporte. "
            "Adapters logger supportes: console"
        )

    @overload
    def repository(
        self,
        entity_class: type[T],
        *,
        registry: None = None,
        mapper_registry: RelationalMapperRegistry | None = None,
    ) -> Repository[T]:
        pass

    @overload
    def repository(
        self,
        entity_class: type[T],
        *,
        registry: RepositoryRegistry[T, R],
        mapper_registry: None = None,
    ) -> R:
        pass

    def repository(
        self,
        entity_class: type[T],
        *,
        registry: RepositoryRegistry[T, R] | None = None,
        mapper_registry: RelationalMapperRegistry | None = None,
    ) -> Repository[T] | R:
        from arclith.infrastructure.repository_factory import build_repository

        if registry is not None and mapper_registry is not None:
            raise ValueError(
                "mapper_registry cannot be combined with a custom RepositoryRegistry"
            )
        repository: Repository[T] | R
        if registry is None:
            repository = build_repository(
                self.config,
                entity_class,
                self.logger,
                mapper_registry=mapper_registry,
            )
        else:
            repository = registry.build(self.config, entity_class, self.logger)
        settings = self.config.adapters.opentelemetry
        if (
            self.config.adapters.observability.is_enabled("opentelemetry")
            and settings is not None
            and settings.instrumentation.repositories
        ):
            from arclith.adapters.outbound.opentelemetry.instrumentations.repository import (
                ObservedRepository,
            )

            return ObservedRepository(
                repository,
                self.tracer(),
                self.metrics(),
            )
        return repository

    def file_storage(
        self,
        *,
        registry: FileStorageRegistry | None = None,
    ) -> FileStoragePort:
        from arclith.infrastructure.file_storage_factory import build_file_storage

        return build_file_storage(self.config, self.logger, registry=registry)

    def channel_sender(
        self,
        adapter: str,
        *,
        registry: ChannelSenderRegistry | None = None,
    ) -> ChannelSender:
        """Build an outbound sender for an explicitly configured channel adapter."""

        from arclith.infrastructure.channel_factory import build_channel_sender

        return build_channel_sender(
            self.config,
            self.logger,
            adapter,
            registry=registry,
        )

    def embedding(
        self,
        *,
        registry: EmbeddingRegistry | None = None,
    ) -> EmbeddingPort:
        from arclith.infrastructure.embedding_factory import build_embedding

        return build_embedding(self.config, self.logger, registry=registry)

    def vector_store(
        self,
        *,
        registry: VectorStoreRegistry | None = None,
    ) -> VectorStorePort:
        from arclith.infrastructure.vector_store_factory import build_vector_store

        return build_vector_store(self.config, self.logger, registry=registry)

    def rabbitmq_command_bus(self) -> "RabbitMQCommandBus":
        if not self.config.command_bus.is_enabled("rabbitmq"):
            raise RuntimeError(
                "command_bus.enabled doit contenir rabbitmq pour utiliser rabbitmq_command_bus()."
            )
        from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus

        trace_rabbitmq = self._langsmith_instrumentation_enabled(
            "command_bus"
        ) or self._opentelemetry_instrumentation_enabled("rabbitmq", "traces")
        tracer = self.tracer() if trace_rabbitmq else None
        metrics = (
            self._observability_runtime.metrics
            if self._opentelemetry_instrumentation_enabled("rabbitmq", "metrics")
            else None
        )
        return RabbitMQCommandBus(
            self.config.command_bus.rabbitmq,
            self.logger,
            tracer=tracer,
            metrics=metrics,
        )

    def run_command_bus(self, dispatcher: "CommandDispatcher") -> None:
        async def _run() -> None:
            bus = self.rabbitmq_command_bus()
            self._start_observability()
            try:
                await bus.run(dispatcher)
            finally:
                await bus.close()
                self.close_observability()

        asyncio.run(_run())

    @cached_property
    def _fastapi_bootstrap(self) -> Any:
        from arclith.infrastructure.fastapi_bootstrap import FastAPIBootstrap

        return FastAPIBootstrap(self)

    def fastapi(self, **kwargs: Any) -> "FastAPI":
        return self._fastapi_bootstrap.fastapi(**kwargs)

    def _configure_fastapi_kwargs(self, kwargs: dict[str, Any]) -> None:
        self._fastapi_bootstrap._configure_fastapi_kwargs(kwargs)

    def _configure_keycloak_swagger(self, kwargs: dict[str, Any]) -> None:
        self._fastapi_bootstrap._configure_keycloak_swagger(kwargs)

    def _add_fastapi_observability(self, app: "FastAPI") -> None:
        self._fastapi_bootstrap._add_fastapi_observability(app)

    def _add_fastapi_http_middlewares(self, app: "FastAPI") -> None:
        self._fastapi_bootstrap._add_fastapi_http_middlewares(app)

    def _patch_openapi_keycloak(self, app: "FastAPI") -> None:
        self._fastapi_bootstrap._patch_openapi_keycloak(app)

    def auth_dependency(self, transport: Literal["api", "mcp"] = "api") -> Callable:
        return self._fastapi_bootstrap.auth_dependency(transport)

    # ── probe helpers ─────────────────────────────────────────────────────────

    def add_readiness_check(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """Register an async readiness check (e.g. DB ping) exposed on /ready."""
        self._probe_server.add_readiness_check(fn)

    @cached_property
    def _mcp_instrumentation(self) -> Any:
        from arclith.infrastructure.mcp_instrumentation import McpInstrumentation

        return McpInstrumentation(self)

    def instrument_mcp(self, mcp: "_fastmcp.FastMCP") -> None:
        self._mcp_instrumentation.instrument_mcp(mcp)

    def run_with_probes(
        self,
        *runners: Callable[[], None],
        transports: list[str] | None = None,
    ) -> None:
        """Start ProbeServer (background daemon) then run service runner(s).

        - 1 runner  → runs in the main thread (blocking, current behaviour).
        - N runners → each in its own non-daemon thread; main thread joins (MODE=all).

        ``transports`` populates /info → active_transports.
        """
        if not runners:
            return

        if transports:
            self._probe_server.set_active_transports(transports)

        if self.config.probe.enabled:
            self._probe_server.start_in_background()

        if len(runners) == 1:
            runners[0]()
            return

        threads = [
            threading.Thread(target=r, daemon=False, name=f"runner-{i}")
            for i, r in enumerate(runners)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # ── runners ───────────────────────────────────────────────────────────────

    def fastmcp(self, name: str, **kwargs: Any) -> "_fastmcp.FastMCP":
        import fastmcp

        return fastmcp.FastMCP(name, **kwargs)

    def tracer(self) -> TracePort:
        """Return the configured provider-neutral tracer (a no-op by default)."""
        return self._trace_adapter

    def metrics(self) -> MetricPort:
        """Return the configured provider-neutral metric recorder."""
        return self._observability_runtime.metrics

    def langsmith_client(self) -> Any:
        """Return the configured native LangSmith client for advanced operations."""
        if not self.config.adapters.observability.is_enabled("langsmith"):
            raise RuntimeError(
                "LangSmith n'est pas active dans adapters.observability.enabled"
            )
        client = getattr(self._observability_runtime, "client", None)
        if not callable(client):
            raise RuntimeError("Le runtime LangSmith ne fournit pas de client")
        return client()

    def pydantic_ai_llm(self) -> Any:
        """Build the configured Pydantic AI adapter with optional tracing."""
        settings = self.config.adapters.lm
        if settings is None:
            raise RuntimeError(
                "config.adapters.lm est requis pour utiliser pydantic_ai_llm()"
            )
        from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter

        instrumentation = self._observability_runtime.pydantic_ai_instrumentation()
        return PydanticAILLMAdapter(settings, instrumentation=instrumentation)

    def flush_observability(self, timeout: float | None = None) -> None:
        self._observability_runtime.force_flush(timeout)

    def close_observability(self, timeout: float | None = None) -> None:
        self._observability_runtime.shutdown(timeout)

    def observability_diagnostics(self) -> Mapping[str, Any]:
        return self._observability_runtime.diagnostics()

    def observability_providers(self) -> Mapping[str, Any]:
        """Return native providers for advanced, explicitly vendor-specific use."""

        return self._observability_runtime.native_providers()

    def langgraph(
        self,
        state_schema: type[Any],
        register_graph: Callable[[Any, "Arclith"], None],
        *,
        context_schema: type[Any] | None = None,
        input_schema: type[Any] | None = None,
        output_schema: type[Any] | None = None,
        name: str = "agent",
        checkpointer: Any = _LANGGRAPH_UNSET,
        cache: Any = None,
        store: Any = _LANGGRAPH_UNSET,
        interrupt_before: Any = None,
        interrupt_after: Any = None,
        debug: bool = False,
        stream_mode: LangGraphStreamMode | Sequence[LangGraphStreamMode] | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        persistence: bool | None = None,
        persistence_registry: LangGraphPersistenceRegistry | None = None,
    ) -> Any:
        return self._langgraph_bootstrap.langgraph(
            state_schema,
            register_graph,
            context_schema=context_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            name=name,
            checkpointer=checkpointer,
            cache=cache,
            store=store,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
            debug=debug,
            stream_mode=stream_mode,
            transformers=transformers,
            persistence=persistence,
            persistence_registry=persistence_registry,
        )

    @cached_property
    def _langgraph_bootstrap(self) -> Any:
        from arclith.infrastructure.langgraph_bootstrap import LangGraphBootstrap

        return LangGraphBootstrap(self)

    def _langsmith_instrumentation_enabled(self, name: str) -> bool:
        settings = self.config.adapters.langsmith
        return bool(
            self.config.adapters.observability.is_enabled("langsmith")
            and settings is not None
            and getattr(settings.instrumentation, name)
        )

    def _opentelemetry_instrumentation_enabled(
        self, name: str, signal: Literal["traces", "metrics", "logs"]
    ) -> bool:
        settings = self.config.adapters.opentelemetry
        return bool(
            self.config.adapters.observability.is_enabled("opentelemetry")
            and settings is not None
            and getattr(settings.instrumentation, name)
            and getattr(settings.signals, signal).enabled
        )

    def langgraph_memory_namespace(self, **values: object) -> tuple[str, ...]:
        return self._langgraph_bootstrap.langgraph_memory_namespace(**values)

    def close_langgraph_persistence(self) -> None:
        self._langgraph_bootstrap.close_langgraph_persistence()

    def run_api(self, app: "FastAPI | str") -> None:
        import uvicorn

        in_main_thread = threading.current_thread() is threading.main_thread()
        uvicorn.run(
            app,  # type: ignore[arg-type]
            host=self.config.api.host,
            port=self.config.api.port,
            reload=self.config.api.reload
            if isinstance(app, str) and in_main_thread
            else False,
            log_config=_UVICORN_LOG_CONFIG,
            ws="websockets-sansio",
        )

    def run_mcp_sse(self, mcp: "_fastmcp.FastMCP") -> None:
        self._start_observability()
        try:
            mcp.run(
                transport="sse", host=self.config.mcp.host, port=self.config.mcp.port
            )
        finally:
            self.close_observability()

    def run_mcp_http(self, mcp: "_fastmcp.FastMCP") -> None:
        self._start_observability()
        try:
            mcp.run(
                transport="streamable-http",
                host=self.config.mcp.host,
                port=self.config.mcp.port,
            )
        finally:
            self.close_observability()

    # ── private cached helpers ────────────────────────────────────────────────

    @cached_property
    def _trace_adapter(self) -> TracePort:
        return self._observability_runtime.tracer

    @cached_property
    def _observability_runtime(self) -> ObservabilityRuntimePort:
        from arclith.infrastructure.observability_factory import (
            build_observability_runtime,
        )

        runtime = build_observability_runtime(
            self.config,
            self.logger,
            anonymizer=self._trace_anonymizer,
            opentelemetry_overrides=self._opentelemetry_overrides,
        )
        configure_logger = getattr(self.logger, "configure_observability", None)
        if callable(configure_logger):
            configure_logger(runtime.correlation, runtime.logs)
        return runtime

    def _start_observability(self) -> None:
        self._observability_runtime.start()

    @cached_property
    def _cache(self) -> Any:
        """CachePort instance shared by JWTDecoder and VaultTenantResolver.

        Uses Redis when ``config.cache.backend == "redis"`` (recommended for production
        and multi-replica deployments), falls back to in-process memory otherwise.
        """
        cache: Any
        if self.config.cache.backend == "redis":
            from arclith.adapters.outbound.redis.cache_adapter import RedisCacheAdapter

            cache = RedisCacheAdapter(self.config.cache.redis_url)
        else:
            from arclith.adapters.outbound.memory.cache_adapter import (
                MemoryCacheAdapter,
            )

            cache = MemoryCacheAdapter()
        settings = self.config.adapters.opentelemetry
        if (
            self.config.adapters.observability.is_enabled("opentelemetry")
            and settings is not None
            and settings.instrumentation.caches
        ):
            from arclith.adapters.outbound.opentelemetry.instrumentations.cache import (
                ObservedCache,
            )

            return ObservedCache(cache, self.tracer(), self.metrics())
        return cache

    @cached_property
    def _metrics_registry(self) -> Any:
        from arclith.adapters.inbound.probes.metrics import MetricsRegistry

        return MetricsRegistry()

    @cached_property
    def _mcp_collector(self) -> Any:
        from arclith.adapters.inbound.probes.metrics import McpMetricsCollector

        collector = McpMetricsCollector(self._metrics_registry, logger=self.logger)
        if self.config.probe.enabled:
            self._probe_server.add_collector(collector)
        return collector

    @cached_property
    def _probe_server(self) -> Any:
        from arclith.adapters.inbound.probes.server import ProbeServer

        probe = self.config.probe
        return ProbeServer(
            host=probe.host,
            port=probe.port,
            service_name=self.config.app.name,
            service_version=self.config.app.version,
        )

    def _setup_uvicorn_logging(self) -> None:
        handler = _UvicornLogInterceptHandler(
            self.logger,
            self._observability_runtime.correlation,
        )
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "watchfiles"):
            log = logging.getLogger(name)
            log.setLevel(logging.DEBUG)
            log.handlers = [handler]
            log.propagate = False
