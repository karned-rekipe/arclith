# Auth Production

Cette page fixe le minimum pour exposer une API ou un MCP Arclith en production.

## Objectif

Un service de production doit refuser toute requête non authentifiée avant
d'entrer dans les use cases.

## Stack Cible

| Besoin | Choix |
|---|---|
| Identity provider | Keycloak |
| Jeton | JWT RS256 |
| Validation | JWKS |
| Autorisation | rôles applicatifs |
| Transports | FastAPI et FastMCP |

## Ajouter L'adapter

```bash
arclith-cli add-adapter \
  --capability auth \
  --adapter keycloak \
  --param url=https://keycloak.example.com \
  --param realm=production \
  --param audience=my-service-api \
  --param client_id=my-service-swagger \
  --yes
```

## Configuration Minimale

```yaml
# config/adapters/inbound/keycloak.yaml
url: "https://keycloak.example.com"
realm: "production"
audience: my-service-api
client_id: my-service-swagger
```

## Règles

- Toujours vérifier `issuer`, `audience`, signature et expiration.
- Garder les rôles métier dans les use cases ou policies applicatives.
- Ne pas copier la logique JWT dans chaque endpoint.
- Activer HTTPS devant Keycloak et devant le service.
- Mettre le cache JWKS dans Redis si le service a plusieurs replicas.

## Vérifier

```bash
uv run pytest
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
```

## Suite

Lire [cache Redis](cache.md), puis la capability [auth/keycloak](../capabilities/auth.md).
