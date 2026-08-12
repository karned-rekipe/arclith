# Capability HTTP

Middlewares HTTP transverses pour FastAPI.

## Objectif

Standardiser les comportements HTTP qui évitent les doubles mutations,
améliorent le cache et sécurisent les mises à jour concurrentes.

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

## Comportements

| Adapter | Entrée | Sortie |
|---|---|---|
| `idempotency` | `Idempotency-Key` sur `POST` | replay d'une réponse déjà traitée |
| `etag` | `If-Match`, `If-None-Match` | version attendue ou `304` |
| `cache-control` | méthode et chemin HTTP | header `Cache-Control` adapté |

## Règles

- En production multi-worker, associer ces middlewares à [cache/redis](cache.md).
- Exiger `Idempotency-Key` sur les mutations critiques.
- Utiliser ETag pour les ressources versionnées.
- Mettre `no-store` sur les mutations et payloads sensibles.
- Tester les headers publics dans les tests API.

## Validation

```bash
curl -i -X POST http://127.0.0.1:8000/v1/items/ \
  -H "Idempotency-Key: demo-1" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Suite

Lire [API](api.md), puis [HTTP](../http-conventions.md).
