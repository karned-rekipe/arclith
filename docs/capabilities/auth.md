# Capability Auth

Authentification JWT Keycloak mutualisée FastAPI et FastMCP.

## Objectif

Centraliser la validation JWT pour éviter une logique différente entre API,
MCP et tenants.

## Adapter

| Adapter | Usage |
|---|---|
| `keycloak` | JWT RS256 via JWKS Keycloak et Swagger UI OAuth2 PKCE |

## Commande

```bash
arclith-cli add-adapter \
  --capability auth \
  --adapter keycloak \
  --param url=http://keycloak:8080 \
  --param realm=rekipe \
  --param audience=rekipe-api \
  --param client_id=swagger-public \
  --yes
```

## Configuration Générée

```yaml
# config/adapters/inbound/keycloak.yaml
url: "http://keycloak:8080"
realm: "rekipe"
audience: rekipe-api
client_id: swagger-public
```

## Utiliser Dans L'API

```python
from fastapi import APIRouter, Depends

require_auth = arclith.auth_dependency()
router = APIRouter(dependencies=[Depends(require_auth)])
```

## Utiliser Dans MCP

```python
require_auth = arclith.auth_dependency(transport="mcp")
```

L'auth MCP nécessite un transport HTTP/SSE qui expose les headers.

## Règles

- Vérifier signature, expiration, issuer et audience.
- Utiliser Redis pour le cache JWKS en multi-worker.
- Garder les décisions métier dans les policies ou use cases.
- Ne pas coder de secret client dans Swagger UI: le client PKCE est public.
- Coupler avec [license](license.md) quand un rôle applicatif est obligatoire.

## Validation

```bash
uv run pytest
curl -fsS http://keycloak:8080/realms/rekipe/.well-known/openid-configuration
```

## Suite

Lire [Auth production](../production/auth.md), puis [Authentification & Autorisation](../auth.md).
