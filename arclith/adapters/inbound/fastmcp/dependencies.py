from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import fastmcp

from arclith.adapters.inbound.auth_pipeline import AuthPipelineError, run_auth_pipeline
from arclith.infrastructure.config import AppConfig

if TYPE_CHECKING:
    from arclith.adapters.inbound.jwt.decoder import JWTDecoder
    from arclith.domain.ports.outbound.license_validator import LicenseValidator
    from arclith.domain.ports.outbound.tenant_resolver import TenantResolver


def make_inject_tenant_uri(
    config: AppConfig,
    *,
    jwt_decoder: "JWTDecoder | None" = None,
    license_validator: "LicenseValidator | None" = None,
    tenant_resolvers: "list[TenantResolver] | None" = None,
) -> Callable:
    """Returns a FastMCP dependency that injects TenantContext for the current request.

    Identical signature to the FastAPI counterpart — both delegate to ``run_auth_pipeline``.
    Only header extraction differs (FastMCP uses ``ctx.request_context``).

    In single-tenant mode (``config.adapters.multitenant`` is False), this is a no-op.
    Raises ``PermissionError`` on auth failure (converted to MCP protocol error).

    Note: only effective on HTTP/SSE transports where request headers are available.
    """

    async def inject_tenant_uri(ctx: fastmcp.Context) -> None:
        if not config.adapters.multitenant:
            return
        if jwt_decoder is None:
            raise RuntimeError("jwt_decoder requis en mode multitenant")
        tenant_claim = config.tenant.tenant_claim if config.tenant else "sub"
        try:
            await run_auth_pipeline(
                _extract_headers(ctx),
                jwt_decoder=jwt_decoder,
                license_validator=license_validator,
                tenant_resolvers=tenant_resolvers or [],
                tenant_claim=tenant_claim,
            )
        except AuthPipelineError as exc:
            raise PermissionError(f"{exc.status_code}: {exc.detail}") from exc

    return inject_tenant_uri


def _extract_headers(ctx: fastmcp.Context) -> dict[str, str]:
    """Extract HTTP headers from a FastMCP context (HTTP/SSE transports only).

    Returns an empty dict if the transport does not expose HTTP headers (e.g. stdio).
    """
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
        if request is None:
            return {}
        return dict(request.headers)
    except Exception:
        return {}
