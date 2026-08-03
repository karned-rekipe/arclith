from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING

from arclith.adapters.context import set_tenant_context
from arclith.domain.models.tenant import TenantContext

if TYPE_CHECKING:
    from arclith.adapters.inbound.jwt.decoder import JWTDecoder
    from arclith.domain.ports.outbound.license_validator import LicenseValidator
    from arclith.domain.ports.outbound.tenant_resolver import TenantResolver


class AuthPipelineError(Exception):
    """Raised when the auth pipeline fails.

    Callers convert to their transport-specific error:
    - FastAPI  → ``HTTPException(status_code, detail)``
    - FastMCP  → ``PermissionError(f"{status_code}: {detail}")``
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _extract_bearer_token(headers: Mapping[str, str]) -> str:
    auth = headers.get("Authorization") or headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthPipelineError(401, "Authorization header manquant ou invalide")
    return auth.removeprefix("Bearer ")


async def _resolve_and_set_tenant(
    claims: dict,
    tenant_resolvers: list[TenantResolver],
    tenant_claim: str,
) -> None:
    tenant_id: str | None = claims.get(tenant_claim)
    if not tenant_id:
        raise AuthPipelineError(401, f"Claim '{tenant_claim}' absent du token")

    results = await asyncio.gather(*[r.resolve(tenant_id) for r in tenant_resolvers])
    merged = TenantContext(
        adapters={
            adapter: coords
            for ctx in results
            for adapter, coords in ctx.adapters.items()
        }
    )
    set_tenant_context(merged)


async def run_auth_pipeline(
    headers: Mapping[str, str],
    *,
    jwt_decoder: JWTDecoder,
    license_validator: LicenseValidator | None = None,
    tenant_resolvers: list[TenantResolver] | None = None,
    tenant_claim: str = "sub",
) -> dict:
    """Core JWT auth pipeline — transport-agnostic.

    Steps:
    1. Extract Bearer token from Authorization header
    2. Decode and validate JWT via Keycloak JWKS (cached)
    3. Check licence via ``LicenseValidator`` (if provided)
    4. Extract ``tenant_id`` from claims using ``tenant_claim``
    5. Resolve ``TenantContext`` in parallel via all ``TenantResolver`` (if provided)
    6. Set ``TenantContext`` on the current async context
    7. Return raw claims dict

    Raises ``AuthPipelineError`` on any failure.
    Callers (FastAPI / FastMCP adapters) convert to transport-specific errors.

    ``tenant_resolvers`` is optional — omit for auth-only (no tenant resolution).
    """
    token = _extract_bearer_token(headers)

    try:
        claims: dict = await jwt_decoder.decode(token)
    except Exception as exc:
        raise AuthPipelineError(401, f"Token JWT invalide : {exc}") from exc

    if license_validator is not None and not license_validator.validate(claims):
        raise AuthPipelineError(403, "Licence invalide ou absente")

    if tenant_resolvers:
        await _resolve_and_set_tenant(claims, tenant_resolvers, tenant_claim)

    return claims
