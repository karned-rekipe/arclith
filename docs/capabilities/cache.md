# Capability Cache

Cache technique pour JWKS, idempotency et résolution tenant.

## Objectif

Partager les données techniques courtes entre API, MCP, agent et workers quand
ils tournent dans plusieurs processus.

## Adapters

| Adapter | Usage |
|---|---|
| `memory` | développement, tests, mono-processus |
| `redis` | production, multi-worker, Kubernetes |

## Commande

```bash
arclith-cli add-adapter --capability cache --adapter redis --yes
```

## Configuration Générée

```yaml
# config/adapters/inbound/cache.yaml
backend: redis
redis_url: ""
jwks_ttl: 3600
tenant_uri_ttl: 300
```

`redis_url` doit être résolu par [secrets](secrets.md) ou par `REDIS_URL`.

## Usages

| Usage | Clé De Décision |
|---|---|
| JWKS Keycloak | réduire les appels à Keycloak |
| Idempotency-Key | rejouer une réponse POST déjà traitée |
| Tenant URI | éviter un appel Vault à chaque requête |

## Règles

- Utiliser Redis dès que plusieurs processus partagent le trafic.
- Définir un TTL court et explicite par usage.
- Préfixer les clés par service et environnement.
- Ne pas stocker de secret brut dans le cache.
- Surveiller erreurs, latence et saturation Redis.

## Validation

```bash
docker run --rm -d --name arclith-redis -p 6379:6379 redis:7-alpine
REDIS_URL=redis://127.0.0.1:6379 uv run pytest
docker stop arclith-redis
```

## Suite

Lire [Cache production](../production/cache.md), puis [HTTP](http.md).
