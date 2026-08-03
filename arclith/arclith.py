from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.logger import Logger, LogLevel
from arclith.domain.ports.repository import Repository
from arclith.infrastructure.config import AppConfig, load_config_dir, load_config_file
from arclith.infrastructure.repository_factory import RepositoryRegistry

if TYPE_CHECKING:
    import fastmcp as _fastmcp
    from fastapi import FastAPI

T = TypeVar("T", bound=Entity)
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
        from arclith.adapters.output.console.logger import ConsoleLogger
        return ConsoleLogger()
    def repository(
        self,
        entity_class: type[T],
        *,
        registry: RepositoryRegistry[T] | None = None,
    ) -> "Repository[T]":
        from arclith.infrastructure.repository_factory import build_repository

        return build_repository(self.config, entity_class, self.logger, registry=registry)
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
            from arclith.adapters.input.probes.metrics import ApiMetricsCollector
            app.add_middleware(ApiMetricsCollector, registry=self._metrics_registry)
            self._probe_server.add_collector(
                ApiMetricsCollector(app=None, registry=self._metrics_registry)  # type: ignore[arg-type]
            )

    def _add_fastapi_http_middlewares(self, app: "FastAPI") -> None:
        # Order matters: Starlette applies the last registered middleware first.
        from arclith.adapters.input.fastapi.timing import TimingMiddleware
        app.add_middleware(TimingMiddleware, logger=self.logger)

        from arclith.adapters.input.fastapi.cache_control import CacheControlMiddleware
        app.add_middleware(
            CacheControlMiddleware,
            logger = self.logger,
            get_single_max_age = self.config.http.cache_control.get_single_max_age,
            get_list_max_age = self.config.http.cache_control.get_list_max_age,
        )

        from arclith.adapters.input.fastapi.etag import ETaggerMiddleware
        if self.config.http.etag.enabled:
            app.add_middleware(ETaggerMiddleware, logger = self.logger)

        from arclith.adapters.input.fastapi.idempotency import IdempotencyMiddleware
        if self.config.http.idempotency.enabled:
            app.add_middleware(
                IdempotencyMiddleware,
                cache = self._cache,
                logger = self.logger,
                ttl = self.config.http.idempotency.ttl_seconds,
                required = self.config.http.idempotency.required,
            )

    def _patch_openapi_keycloak(self, app: "FastAPI") -> None:
        """Inject Keycloak OAuth2 PKCE security scheme into the OpenAPI spec.

        Adds ``components.securitySchemes.keycloak`` so Swagger UI shows an
        "Authorize" button that triggers the PKCE flow against Keycloak.
        Endpoints using ``make_require_auth`` / ``HTTPBearer`` also expose
        the ``bearerAuth`` scheme automatically via FastAPI introspection.
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
            schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
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
            # The server still accepts any valid Bearer token — HTTPBearer stays
            # in securitySchemes for programmatic clients.
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
        from arclith.adapters.input.jwt.decoder import JWTDecoder
        from arclith.adapters.input.license.validator import RoleLicenseValidator

        kc = self.config.keycloak
        decoder = JWTDecoder(
            jwks_uri=f"{kc.url}/realms/{kc.realm}/protocol/openid-connect/certs",
            audience=kc.audience,
            cache=self._cache,
            ttl_s=self.config.cache.jwks_ttl,
        )
        license_validator = (
            RoleLicenseValidator(self.config.license.role) if self.config.license else None
        )

        if transport == "mcp":
            from arclith.adapters.input.fastmcp.auth import make_require_auth_tool
            return make_require_auth_tool(jwt_decoder=decoder, license_validator=license_validator)

        from arclith.adapters.input.fastapi.auth import make_require_auth
        return make_require_auth(jwt_decoder=decoder, license_validator=license_validator)

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
            self.logger.warning("⚠️ instrument_mcp: cannot access FastMCP components (API changed?)")
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

    def run_api(self, app: "FastAPI | str") -> None:
        import uvicorn
        in_main_thread = threading.current_thread() is threading.main_thread()
        uvicorn.run(
            app,  # type: ignore[arg-type]
            host=self.config.api.host,
            port=self.config.api.port,
            reload=self.config.api.reload if isinstance(app, str) and in_main_thread else False,
            log_config=_UVICORN_LOG_CONFIG,
            ws="websockets-sansio",
        )


    def run_mcp_sse(self, mcp: "_fastmcp.FastMCP") -> None:
        mcp.run(transport="sse", host=self.config.mcp.host, port=self.config.mcp.port)

    def run_mcp_http(self, mcp: "_fastmcp.FastMCP") -> None:
        mcp.run(transport="streamable-http", host=self.config.mcp.host, port=self.config.mcp.port)

    # ── private cached helpers ────────────────────────────────────────────────

    @cached_property
    def _cache(self) -> Any:
        """CachePort instance shared by JWTDecoder and VaultTenantResolver.

        Uses Redis when ``config.cache.backend == "redis"`` (recommended for production
        and multi-replica deployments), falls back to in-process memory otherwise.
        """
        if self.config.cache.backend == "redis":
            from arclith.adapters.output.redis.cache_adapter import RedisCacheAdapter
            return RedisCacheAdapter(self.config.cache.redis_url)
        from arclith.adapters.output.memory.cache_adapter import MemoryCacheAdapter
        return MemoryCacheAdapter()

    @cached_property
    def _metrics_registry(self) -> Any:
        from arclith.adapters.input.probes.metrics import MetricsRegistry
        return MetricsRegistry()

    @cached_property
    def _mcp_collector(self) -> Any:
        from arclith.adapters.input.probes.metrics import McpMetricsCollector
        collector = McpMetricsCollector(self._metrics_registry, logger=self.logger)
        if self.config.probe.enabled:
            self._probe_server.add_collector(collector)
        return collector

    @cached_property
    def _probe_server(self) -> Any:
        from arclith.adapters.input.probes.server import ProbeServer
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
