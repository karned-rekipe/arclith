# Capability Cache

Cache technique pour JWKS, idempotency et résolution tenant.

## Adapters

| Adapter | Usage |
|---|---|
| `memory` | développement, tests, mono-processus |
| `redis` | production, multi-worker, Kubernetes |

## Commande

```bash
arclith-cli add-adapter --capability cache --adapter redis --yes
```

## Configuration

```yaml
# config/adapters/inbound/cache.yaml
backend: redis
redis_url: ""
jwks_ttl: 3600
tenant_uri_ttl: 300
```

## Règle

Utiliser Redis dès que API, MCP, agent ou workers tournent dans des processus séparés.

## Validation

```bash
docker run --rm -d --name arclith-redis -p 6379:6379 redis:7-alpine
REDIS_URL=redis://127.0.0.1:6379 uv run pytest
docker rm -f arclith-redis
```

## Suite

Lire [HTTP](http.md) pour l'idempotence et les headers cache.
