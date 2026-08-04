from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import HTTPException, Request

from arclith.adapters.inbound.auth_pipeline import AuthPipelineError, run_auth_pipeline
from arclith.adapters.inbound.jwt.decoder import JWTDecoder
from arclith.domain.ports.outbound.license_validator import LicenseValidator
from arclith.domain.ports.outbound.tenant_resolver import TenantResolver
from arclith.infrastructure.config import AppConfig


def make_inject_tenant_uri(
    config: AppConfig,
    *,
    jwt_decoder: JWTDecoder | None = None,
    license_validator: LicenseValidator | None = None,
    tenant_resolvers: list[TenantResolver] | None = None,
) -> Callable:
    """Retourne une dépendance FastAPI qui injecte le TenantContext pour la requête courante.

    En mode **single-tenant** (``config.adapters.multitenant`` est False), la dépendance
    est un no-op : les adapters utilisent directement leur config statique.

    En mode **multi-tenant**, le pipeline complet s'exécute :
    1. Extraction et validation du JWT (Keycloak JWKS, mis en cache)
    2. Vérification de la licence (realm role)
    3. Résolution parallèle de **tous** les resolvers tenant (un par adaptateur multitenant)
    4. Merge des TenantContexts → un seul TenantContext par requête

    ``tenant_resolvers`` est une **liste** — un resolver par adaptateur multitenant.
    Exemple : ``[VaultTenantResolver("mongodb", ...), VaultTenantResolver("s3_client", ...)]``
    Les adaptateurs non-multitenant (bucket applicatif partagé, etc.) ne sont pas listés ici.
    """

    async def inject_tenant_uri(request: Request) -> None:
        if not config.adapters.multitenant:
            return
        if jwt_decoder is None:
            raise RuntimeError("jwt_decoder requis en mode multitenant")
        tenant_claim = config.tenant.tenant_claim if config.tenant else "sub"
        try:
            await run_auth_pipeline(
                request.headers,
                jwt_decoder=jwt_decoder,
                license_validator=license_validator,
                tenant_resolvers=tenant_resolvers or [],
                tenant_claim=tenant_claim,
            )
        except AuthPipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return inject_tenant_uri


async def get_duration_ms(request: Request) -> float:
    """FastAPI dependency — returns elapsed ms since request start.

    Requires ``TimingMiddleware`` to be active (injected by ``Arclith.fastapi()``).
    Returns 0.0 if middleware is absent.

    Usage::

        async def my_endpoint(duration_ms: Annotated[float, Depends(get_duration_ms)]):
            return success_response(data, metadata=ResponseMetadata(duration_ms=int(duration_ms)))
    """
    start: float | None = getattr(request.state, "start_time", None)
    if start is None:
        return 0.0
    return round((time.monotonic() - start) * 1000)
