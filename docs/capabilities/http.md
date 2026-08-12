# Capability HTTP

Middlewares HTTP transverses pour FastAPI.

## Adapters

| Adapter | Usage |
|---|---|
| `idempotency` | évite les doubles mutations `POST` |
| `etag` | revalidation des lectures `GET` |
| `cache-control` | headers de cache HTTP |

## Commande

```bash
arclith-cli add-adapter --capability http --adapter idempotency --yes
arclith-cli add-adapter --capability http --adapter etag --yes
arclith-cli add-adapter --capability http --adapter cache-control --yes
```

## Configuration

```yaml
# config/http.yaml
idempotency:
  enabled: true
  ttl_seconds: 86400
  required: false
etag:
  enabled: true
cache_control:
  get_single_max_age: 300
  get_list_max_age: 60
```

## Règle

En production multi-worker, associer ces middlewares à [cache/redis](cache.md).

## Validation

```bash
curl -i -X POST http://127.0.0.1:8000/v1/items/ \
  -H "Idempotency-Key: demo-1" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Suite

Lire [HTTP](../http-conventions.md).
