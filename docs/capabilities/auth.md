# Capability Auth

Authentification JWT Keycloak mutualisée FastAPI et FastMCP.

## Adapter

| Adapter | Usage |
|---|---|
| `keycloak` | JWT RS256 via JWKS Keycloak |

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

## Configuration

```yaml
# config/adapters/inbound/keycloak.yaml
url: "http://keycloak:8080"
realm: "rekipe"
audience: rekipe-api
client_id: swagger-public
```

## Règle

La vérification JWT est commune aux transports API et MCP.

## Validation

```bash
uv run pytest
```

## Suite

Lire [Authentification & Autorisation](../auth.md).
