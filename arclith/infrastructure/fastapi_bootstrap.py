from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

if TYPE_CHECKING:
    from fastapi import FastAPI

    from arclith.arclith import Arclith


class FastAPIBootstrap:
    """Build and configure FastAPI without bloating the public facade."""

    def __init__(self, owner: "Arclith") -> None:
        self._owner = owner

    def fastapi(self, **kwargs: Any) -> "FastAPI":
        from fastapi import FastAPI

        self._owner._configure_fastapi_kwargs(kwargs)
        user_lifespan = kwargs.pop("lifespan", None)

        @asynccontextmanager
        async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
            self._owner._setup_uvicorn_logging()
            self._owner._start_observability()
            try:
                if user_lifespan is not None:
                    async with AsyncExitStack() as stack:
                        await stack.enter_async_context(user_lifespan(app))
                        yield
                else:
                    yield
            finally:
                self._owner.close_observability()

        app = FastAPI(lifespan=_lifespan, **kwargs)
        self._owner._add_fastapi_observability(app)
        self._owner._add_fastapi_http_middlewares(app)
        self._owner._observability_runtime.instrument_fastapi(app)

        if self._owner.config.keycloak:
            self._owner._patch_openapi_keycloak(app)

        return app

    def _configure_fastapi_kwargs(self, kwargs: dict[str, Any]) -> None:
        kwargs.setdefault("title", self._owner.config.app.name)
        kwargs.setdefault("version", self._owner.config.app.version)
        kwargs.setdefault("description", self._owner.config.app.description)
        if self._owner.config.keycloak:
            self._owner._configure_keycloak_swagger(kwargs)

    def _configure_keycloak_swagger(self, kwargs: dict[str, Any]) -> None:
        kc = self._owner.config.keycloak
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
        if self._owner.config.probe.enabled:
            from arclith.adapters.inbound.probes.metrics import ApiMetricsCollector

            app.add_middleware(
                ApiMetricsCollector, registry=self._owner._metrics_registry
            )
            self._owner._probe_server.add_collector(
                ApiMetricsCollector(app=None, registry=self._owner._metrics_registry)  # type: ignore[arg-type]
            )

    def _add_fastapi_http_middlewares(self, app: "FastAPI") -> None:
        # Order matters: Starlette applies the last registered middleware first.
        from arclith.adapters.inbound.fastapi.timing import TimingMiddleware

        app.add_middleware(TimingMiddleware, logger=self._owner.logger)

        from arclith.adapters.inbound.fastapi.cache_control import (
            CacheControlMiddleware,
        )

        app.add_middleware(
            CacheControlMiddleware,
            logger=self._owner.logger,
            get_single_max_age=self._owner.config.http.cache_control.get_single_max_age,
            get_list_max_age=self._owner.config.http.cache_control.get_list_max_age,
        )

        from arclith.adapters.inbound.fastapi.etag import ETaggerMiddleware

        if self._owner.config.http.etag.enabled:
            app.add_middleware(ETaggerMiddleware, logger=self._owner.logger)

        from arclith.adapters.inbound.fastapi.idempotency import IdempotencyMiddleware

        if self._owner.config.http.idempotency.enabled:
            app.add_middleware(
                IdempotencyMiddleware,
                cache=self._owner._cache,
                logger=self._owner.logger,
                ttl=self._owner.config.http.idempotency.ttl_seconds,
                required=self._owner.config.http.idempotency.required,
            )

    def _patch_openapi_keycloak(self, app: "FastAPI") -> None:
        """Inject Keycloak OAuth2 PKCE security scheme into the OpenAPI spec.

        Adds ``components.securitySchemes.keycloak`` so Swagger UI shows an
        "Authorize" button that triggers the PKCE flow against Keycloak.
        Endpoints using ``make_require_auth`` / ``HTTPBearer`` also expose
        the same runtime bearer dependency; the OpenAPI schema is rewritten so
        Swagger UI presents only the Keycloak OAuth2 flow.
        """
        kc = self._owner.config.keycloak
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
        if self._owner.config.keycloak is None:
            raise RuntimeError(
                "config.keycloak est requis pour utiliser auth_dependency(). "
                "Ajouter la section keycloak dans config.yaml."
            )
        from arclith.adapters.inbound.jwt.decoder import JWTDecoder
        from arclith.adapters.inbound.license.validator import RoleLicenseValidator

        kc = self._owner.config.keycloak
        decoder = JWTDecoder(
            jwks_uri=f"{kc.url}/realms/{kc.realm}/protocol/openid-connect/certs",
            audience=kc.audience,
            cache=self._owner._cache,
            ttl_s=self._owner.config.cache.jwks_ttl,
        )
        license_validator = (
            RoleLicenseValidator(self._owner.config.license.role)
            if self._owner.config.license
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
