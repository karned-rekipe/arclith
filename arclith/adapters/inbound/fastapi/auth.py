from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arclith.adapters.inbound.auth_pipeline import AuthPipelineError, run_auth_pipeline

if TYPE_CHECKING:
    from arclith.adapters.inbound.jwt.decoder import JWTDecoder
    from arclith.domain.ports.outbound.license_validator import LicenseValidator

# Module-level bearer scheme instance — shared across all require_auth instances.
# Registering it here ensures FastAPI adds "HTTPBearer" to the OpenAPI securitySchemes,
# which makes the "Authorize" button appear in Swagger UI.
_http_bearer = HTTPBearer(auto_error=False)


def make_require_auth(
    *,
    jwt_decoder: "JWTDecoder",
    license_validator: "LicenseValidator | None" = None,
) -> Callable:
    """Returns a FastAPI dependency that enforces authentication on specific routes.

    Usage — protect an entire router::

        require_auth = arclith.auth_dependency()
        router = APIRouter(dependencies=[Depends(require_auth)])

    Usage — inject claims in an endpoint::

        async def my_endpoint(claims: Annotated[dict, Depends(require_auth)]) -> ...:
            user_id = claims.get("sub")

    No tenant resolution. Use ``make_inject_tenant_uri`` for the full multitenant pipeline.
    Raises ``HTTPException(401)`` if the token is missing or invalid.
    Raises ``HTTPException(403)`` if the licence check fails.
    """

    async def require_auth(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(_http_bearer)
        ],
    ) -> dict:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Authorization header manquant ou invalide")
        try:
            return await run_auth_pipeline(
                {"Authorization": f"Bearer {credentials.credentials}"},
                jwt_decoder=jwt_decoder,
                license_validator=license_validator,
            )
        except AuthPipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return require_auth

