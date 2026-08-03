from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import fastmcp

from arclith.adapters.inbound.auth_pipeline import AuthPipelineError, run_auth_pipeline
from arclith.adapters.inbound.fastmcp.dependencies import _extract_headers

if TYPE_CHECKING:
    from arclith.adapters.inbound.jwt.decoder import JWTDecoder
    from arclith.domain.ports.outbound.license_validator import LicenseValidator


def make_require_auth_tool(
    *,
    jwt_decoder: JWTDecoder,
    license_validator: LicenseValidator | None = None,
) -> Callable:
    """Returns a FastMCP dependency that enforces authentication on specific tools.

    Usage::

        require_auth = arclith.auth_dependency(transport="mcp")

        @mcp.tool
        async def my_tool(
            name: str,
            ctx: fastmcp.Context,
            _auth: Annotated[dict, Depends(require_auth)],
        ) -> str:
            ...

    No tenant resolution. Use ``make_inject_tenant_uri`` for the full multitenant pipeline.
    Raises ``PermissionError`` on auth failure (converted to MCP protocol error).

    Note: only effective on HTTP/SSE transports where request headers are available.
    On stdio transport, auth headers are unavailable — protect at the network level instead.
    """

    async def require_auth(ctx: fastmcp.Context) -> dict:
        try:
            return await run_auth_pipeline(
                _extract_headers(ctx),
                jwt_decoder=jwt_decoder,
                license_validator=license_validator,
            )
        except AuthPipelineError as exc:
            raise PermissionError(f"{exc.status_code}: {exc.detail}") from exc

    return require_auth
