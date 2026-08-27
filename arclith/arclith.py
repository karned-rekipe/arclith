from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, TypeVar, overload

from arclith.adapters.outbound.opentelemetry.correlation import (
    log_record_trace_metadata,
)
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.file_storage import FileStoragePort
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import (
    AppConfig,
    LangGraphPersistenceSettings,
    LangGraphStreamMode,
    load_config_dir,
    load_config_file,
)
from arclith.infrastructure.file_storage_factory import FileStorageRegistry
from arclith.infrastructure.repository_factory import RepositoryRegistry

if TYPE_CHECKING:
    import fastmcp as _fastmcp
    from fastapi import FastAPI
    from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus
    from arclith.application.command_bus import CommandDispatcher
    from arclith.infrastructure.langgraph_persistence_factory import (
        LangGraphPersistenceComponents,
        LangGraphPersistenceRegistry,
    )

T = TypeVar("T", bound=Entity)
R = TypeVar("R", bound=Repository[Any])
_LANGGRAPH_UNSET = object()
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


def _normalize_langgraph_stream_mode(
    stream_mode: LangGraphStreamMode | Sequence[LangGraphStreamMode],
) -> LangGraphStreamMode | list[LangGraphStreamMode]:
    if isinstance(stream_mode, str):
        return stream_mode
    return list(stream_mode)


def _langgraph_persistence_settings(
    config: AppConfig,
) -> LangGraphPersistenceSettings | None:
    if config.langgraph is None:
        return None
    return config.langgraph.persistence


def _langgraph_persistence_requested(
    settings: LangGraphPersistenceSettings | None,
    override: bool | None,
) -> bool:
    if override is not None:
        return override
    return settings is not None and settings.enabled


def _require_langgraph_persistence(
    settings: LangGraphPersistenceSettings | None,
) -> LangGraphPersistenceSettings:
    if settings is None or not settings.enabled:
        raise RuntimeError(
            "persistence=True requiert langgraph.persistence.enabled=true dans la configuration Arclith"
        )
    return settings


def _langgraph_compile_value(value: Any) -> Any:
    return None if value is _LANGGRAPH_UNSET else value


def _langgraph_configured_value(explicit: Any, configured: object | None) -> Any:
    return configured if explicit is _LANGGRAPH_UNSET else explicit


class _UvicornLogInterceptHandler(logging.Handler):
    def __init__(self, logger: Logger) -> None:
        super().__init__()
        self._logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.exc_info:
            exc = record.exc_info[1]
            tb = "".join(traceback.format_exception(exc))
            message = f"{message}\n{tb}"
        self._logger.log(
            _LEVEL_MAP.get(record.levelname, LogLevel.INFO),
            message,
            **log_record_trace_metadata(record),
        )


class Arclith:
    def __init__(self, config_path: str | Path) -> None:
        p = Path(config_path)
        if p.is_dir():
            self.config: AppConfig = load_config_dir(p)
        elif p.is_file():
            self.config = load_config_file(p)
        else:
            raise ValueError(f"Config path not found: {p}")

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
    ) -> Repository[T]:
        pass

    @overload
    def repository(
        self,
        entity_class: type[T],
        *,
        registry: RepositoryRegistry[T, R],
    ) -> R:
        pass

    def repository(
        self,
        entity_class: type[T],
        *,
        registry: RepositoryRegistry[T, R] | None = None,
    ) -> Repository[T] | R:
        from arclith.infrastructure.repository_factory import build_repository

        return build_repository(
            self.config, entity_class, self.logger, registry=registry
        )

    def file_storage(
        self,
        *,
        registry: FileStorageRegistry | None = None,
    ) -> FileStoragePort:
        from arclith.infrastructure.file_storage_factory import build_file_storage

        return build_file_storage(self.config, self.logger, registry=registry)

    def rabbitmq_command_bus(self) -> "RabbitMQCommandBus":
        if not self.config.command_bus.is_enabled("rabbitmq"):
            raise RuntimeError(
                "command_bus.enabled doit contenir rabbitmq pour utiliser rabbitmq_command_bus()."
            )
        from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus

        return RabbitMQCommandBus(self.config.command_bus.rabbitmq, self.logger)

    def run_command_bus(self, dispatcher: "CommandDispatcher") -> None:
        async def _run() -> None:
            bus = self.rabbitmq_command_bus()
            try:
                await bus.run(dispatcher)
            finally:
                await bus.close()

        asyncio.run(_run())

    def fastapi(self, **kwargs: Any) -> "FastAPI":
        from fastapi import FastAPI

        self._configure_fastapi_kwargs(kwargs)
        user_lifespan = kwargs.pop("lifespan", None)

        @asynccontextmanager
        async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
            self._setup_uvicorn_logging()
            if user_lifespan is not None:
                async with AsyncExitStack() as stack:
                    await stack.enter_async_context(user_lifespan(app))
                    yield
            else:
                yield

        app = FastAPI(lifespan=_lifespan, **kwargs)
        self._add_fastapi_observability(app)
        self._add_fastapi_http_middlewares(app)
        if self.config.adapters.observability.is_enabled("opentelemetry"):
            self._instrument_fastapi_opentelemetry(app)

        if self.config.keycloak:
            self._patch_openapi_keycloak(app)

        return app

    def _configure_fastapi_kwargs(self, kwargs: dict[str, Any]) -> None:
        kwargs.setdefault("title", self.config.app.name)
        kwargs.setdefault("version", self.config.app.version)
        kwargs.setdefault("description", self.config.app.description)
        if self.config.keycloak:
            self._configure_keycloak_swagger(kwargs)

    def _configure_keycloak_swagger(self, kwargs: dict[str, Any]) -> None:
        kc = self.config.keycloak
        if kc is None:
            return
        client_id = kc.client_id or kc.audience or "arclith-client"
        kwargs.setdefault(
            "swagger_ui_init_oauth",
            {
                "clientId": client_id,
                "usePkceWithAuthorizationCodeGrant": True,
                "scopes": "openid profile",
                "additionalQueryStringParams": {"prompt": "login"},
            },
        )
        kwargs.setdefault("swagger_ui_oauth2_redirect_url", "/docs/oauth2-redirect")
        kwargs.setdefault("swagger_ui_parameters", {"persistAuthorization": True})

    def _add_fastapi_observability(self, app: "FastAPI") -> None:
        if self.config.probe.enabled:
            from arclith.adapters.inbound.probes.metrics import ApiMetricsCollector

            app.add_middleware(ApiMetricsCollector, registry=self._metrics_registry)
            self._probe_server.add_collector(
                ApiMetricsCollector(app=None, registry=self._metrics_registry)  # type: ignore[arg-type]
            )

    def _instrument_fastapi_opentelemetry(self, app: "FastAPI") -> None:
        settings = self.config.adapters.opentelemetry
        if settings is None:
            return

        from arclith.adapters.outbound.opentelemetry.fastapi import (
            instrument_fastapi_app,
        )

        instrument_fastapi_app(
            app,
            settings,
            service_name=self.config.app.name,
            service_version=self.config.app.version,
        )

    def _add_fastapi_http_middlewares(self, app: "FastAPI") -> None:
        # Order matters: Starlette applies the last registered middleware first.
        from arclith.adapters.inbound.fastapi.timing import TimingMiddleware

        app.add_middleware(TimingMiddleware, logger=self.logger)

        from arclith.adapters.inbound.fastapi.cache_control import (
            CacheControlMiddleware,
        )

        app.add_middleware(
            CacheControlMiddleware,
            logger=self.logger,
            get_single_max_age=self.config.http.cache_control.get_single_max_age,
            get_list_max_age=self.config.http.cache_control.get_list_max_age,
        )

        from arclith.adapters.inbound.fastapi.etag import ETaggerMiddleware

        if self.config.http.etag.enabled:
            app.add_middleware(ETaggerMiddleware, logger=self.logger)

        from arclith.adapters.inbound.fastapi.idempotency import IdempotencyMiddleware

        if self.config.http.idempotency.enabled:
            app.add_middleware(
                IdempotencyMiddleware,
                cache=self._cache,
                logger=self.logger,
                ttl=self.config.http.idempotency.ttl_seconds,
                required=self.config.http.idempotency.required,
            )

    def _patch_openapi_keycloak(self, app: "FastAPI") -> None:
        """Inject Keycloak OAuth2 PKCE security scheme into the OpenAPI spec.

        Adds ``components.securitySchemes.keycloak`` so Swagger UI shows an
        "Authorize" button that triggers the PKCE flow against Keycloak.
        Endpoints using ``make_require_auth`` / ``HTTPBearer`` also expose
        the same runtime bearer dependency; the OpenAPI schema is rewritten so
        Swagger UI presents only the Keycloak OAuth2 flow.
        """
        kc = self.config.keycloak
        if kc is None:
            return
        base = f"{kc.url}/realms/{kc.realm}/protocol/openid-connect"
        _original = app.openapi

        def _patched_openapi() -> dict:
            if app.openapi_schema:
                return app.openapi_schema
            schema: dict = _original()
            schemes = schema.setdefault("components", {}).setdefault(
                "securitySchemes", {}
            )
            schemes["keycloak"] = {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": f"{base}/auth",
                        "tokenUrl": f"{base}/token",
                        "scopes": {
                            "openid": "OpenID Connect",
                            "profile": "User profile",
                        },
                    }
                },
            }
            # Remove HTTPBearer from securitySchemes: it was auto-added by FastAPI
            # but we want the Swagger UI dialog to only show the keycloak OAuth2 section
            schemes.pop("HTTPBearer", None)

            # Replace HTTPBearer with keycloak in route security so Swagger UI
            # only shows the OAuth2 scheme (no confusing empty HTTPBearer field).
            # The server still accepts any valid Bearer token at runtime because
            # HTTPBearer remains the FastAPI dependency implementation.
            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    if not isinstance(operation, dict):
                        continue
                    security = operation.get("security")
                    if security is None:
                        continue
                    has_bearer = any("HTTPBearer" in s for s in security)
                    has_keycloak = any("keycloak" in s for s in security)
                    if has_bearer and not has_keycloak:
                        operation["security"] = [
                            s for s in security if "HTTPBearer" not in s
                        ] + [{"keycloak": ["openid", "profile"]}]
            app.openapi_schema = schema
            return schema

        app.openapi = _patched_openapi  # type: ignore[method-assign]

    def auth_dependency(self, transport: Literal["api", "mcp"] = "api") -> Callable:
        """Build a ``require_auth`` dependency from the current Keycloak config.

        Requires ``config.keycloak`` to be set.

        - ``transport="api"`` → FastAPI dependency (use with ``Depends()``)
        - ``transport="mcp"`` → FastMCP dependency (use in tool signature)

        Returns a callable that validates the JWT and optional licence.
        No tenant resolution — use ``make_inject_tenant_uri`` for the full pipeline.

        Usage (FastAPI router)::

            require_auth = arclith.auth_dependency()
            router = APIRouter(dependencies=[Depends(require_auth)])

        Usage (FastMCP tool)::

            require_auth = arclith.auth_dependency(transport="mcp")

            @mcp.tool
            async def my_tool(ctx: fastmcp.Context, _auth=Depends(require_auth)) -> str:
                ...
        """
        if self.config.keycloak is None:
            raise RuntimeError(
                "config.keycloak est requis pour utiliser auth_dependency(). "
                "Ajouter la section keycloak dans config.yaml."
            )
        from arclith.adapters.inbound.jwt.decoder import JWTDecoder
        from arclith.adapters.inbound.license.validator import RoleLicenseValidator

        kc = self.config.keycloak
        decoder = JWTDecoder(
            jwks_uri=f"{kc.url}/realms/{kc.realm}/protocol/openid-connect/certs",
            audience=kc.audience,
            cache=self._cache,
            ttl_s=self.config.cache.jwks_ttl,
        )
        license_validator = (
            RoleLicenseValidator(self.config.license.role)
            if self.config.license
            else None
        )

        if transport == "mcp":
            from arclith.adapters.inbound.fastmcp.auth import make_require_auth_tool

            return make_require_auth_tool(
                jwt_decoder=decoder, license_validator=license_validator
            )

        from arclith.adapters.inbound.fastapi.auth import make_require_auth

        return make_require_auth(
            jwt_decoder=decoder, license_validator=license_validator
        )

    # ── probe helpers ─────────────────────────────────────────────────────────

    def add_readiness_check(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """Register an async readiness check (e.g. DB ping) exposed on /ready."""
        self._probe_server.add_readiness_check(fn)

    def instrument_mcp(self, mcp: "_fastmcp.FastMCP") -> None:
        """Wrap all registered FastMCP tools with McpMetricsCollector (Option B).

        Call AFTER all tools are registered::

            IngredientMCP(service, logger, mcp)
            arclith.instrument_mcp(mcp)
        """
        if not self.config.probe.enabled:
            return
        collector = self._mcp_collector
        try:
            # fastmcp 3.x: tools live in _local_provider._components as FunctionTool objects
            components: dict[str, Any] = mcp._local_provider._components  # type: ignore[attr-defined]
        except AttributeError:
            self.logger.warning(
                "⚠️ instrument_mcp: cannot access FastMCP components (API changed?)"
            )
            return
        count = 0
        for component in components.values():
            fn = getattr(component, "fn", None)
            if fn is None or not callable(fn):
                continue
            component.fn = collector.wrap(component.name, fn)
            count += 1
        self.logger.info("🔬 MCP tools instrumented", count=count)

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
        from langgraph.graph import StateGraph

        builder = StateGraph(
            state_schema,
            context_schema=context_schema,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        register_graph(builder, self)
        (
            resolved_checkpointer,
            resolved_store,
            persistence_components,
        ) = self._resolve_langgraph_persistence(
            checkpointer=checkpointer,
            store=store,
            persistence=persistence,
            registry=persistence_registry,
        )
        try:
            compiled = builder.compile(
                checkpointer=resolved_checkpointer,
                cache=cache,
                store=resolved_store,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                debug=debug,
                name=name,
                transformers=transformers,
            )
        except BaseException:
            if persistence_components is not None:
                persistence_components.close()
            raise
        if persistence_components is not None:
            self._remember_langgraph_persistence(persistence_components)
            setattr(compiled, "_arclith_persistence", persistence_components)
        resolved_stream_mode = stream_mode
        if resolved_stream_mode is None and self.config.langgraph is not None:
            resolved_stream_mode = self.config.langgraph.stream_mode
        if resolved_stream_mode is not None:
            setattr(
                compiled,
                "stream_mode",
                _normalize_langgraph_stream_mode(resolved_stream_mode),
            )
        return compiled

    def _resolve_langgraph_persistence(
        self,
        *,
        checkpointer: Any,
        store: Any,
        persistence: bool | None,
        registry: LangGraphPersistenceRegistry | None,
    ) -> tuple[Any, Any, "LangGraphPersistenceComponents | None"]:
        checkpointer_is_explicit = checkpointer is not _LANGGRAPH_UNSET
        store_is_explicit = store is not _LANGGRAPH_UNSET
        persistence_settings = _langgraph_persistence_settings(self.config)
        if not _langgraph_persistence_requested(persistence_settings, persistence):
            return _langgraph_compile_value(checkpointer), _langgraph_compile_value(store), None
        if checkpointer_is_explicit and store_is_explicit:
            return checkpointer, store, None

        persistence_settings = _require_langgraph_persistence(persistence_settings)
        from arclith.infrastructure.langgraph_persistence_factory import (
            build_langgraph_persistence,
        )

        components = build_langgraph_persistence(
            persistence_settings,
            registry=registry,
            include_checkpointer=not checkpointer_is_explicit,
            include_store=not store_is_explicit,
        )
        resolved_checkpointer = _langgraph_configured_value(
            checkpointer, components.checkpointer
        )
        resolved_store = _langgraph_configured_value(store, components.store)
        if components.mode == "agent_server":
            components.close()
            return resolved_checkpointer, resolved_store, None
        return resolved_checkpointer, resolved_store, components

    def langgraph_memory_namespace(self, **values: object) -> tuple[str, ...]:
        settings = (
            self.config.langgraph.persistence
            if self.config.langgraph is not None
            else None
        )
        if settings is None:
            raise RuntimeError("langgraph.persistence n'est pas configure")
        from arclith.infrastructure.langgraph_persistence_factory import (
            render_langgraph_namespace,
        )

        return render_langgraph_namespace(settings.store.namespace_template, values)

    def close_langgraph_persistence(self) -> None:
        resources: list[LangGraphPersistenceComponents] = self.__dict__.pop(
            "_langgraph_persistence_resources", []
        )
        for resource in reversed(resources):
            resource.close()

    def _remember_langgraph_persistence(
        self, components: "LangGraphPersistenceComponents"
    ) -> None:
        resources = self.__dict__.setdefault("_langgraph_persistence_resources", [])
        resources.append(components)

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
        mcp.run(transport="sse", host=self.config.mcp.host, port=self.config.mcp.port)

    def run_mcp_http(self, mcp: "_fastmcp.FastMCP") -> None:
        mcp.run(
            transport="streamable-http",
            host=self.config.mcp.host,
            port=self.config.mcp.port,
        )

    # ── private cached helpers ────────────────────────────────────────────────

    @cached_property
    def _cache(self) -> Any:
        """CachePort instance shared by JWTDecoder and VaultTenantResolver.

        Uses Redis when ``config.cache.backend == "redis"`` (recommended for production
        and multi-replica deployments), falls back to in-process memory otherwise.
        """
        if self.config.cache.backend == "redis":
            from arclith.adapters.outbound.redis.cache_adapter import RedisCacheAdapter

            return RedisCacheAdapter(self.config.cache.redis_url)
        from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter

        return MemoryCacheAdapter()

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
        handler = _UvicornLogInterceptHandler(self.logger)
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "watchfiles"):
            log = logging.getLogger(name)
            log.setLevel(logging.DEBUG)
            log.handlers = [handler]
            log.propagate = False
