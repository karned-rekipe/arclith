# Cache Production

Cette page explique quand passer du cache mémoire à Redis.

## Objectif

Le cache doit être partagé dès que le service tourne avec plusieurs processus,
workers ou replicas.

## Stack Cible

| Besoin | Choix |
|---|---|
| Local/test | `memory` |
| Production | Redis |
| Données typiques | JWKS, idempotence, résolution tenant |
| Expiration | TTL explicite par usage |

## Ajouter L'adapter

```bash
arclith-cli add-adapter --capability cache --adapter redis --yes
```

## Configuration Minimale

```yaml
# config/adapters/inbound/cache.yaml
backend: redis
redis_url: "${REDIS_URL}"
jwks_ttl: 3600
tenant_uri_ttl: 300
```

## Variables

```bash
export REDIS_URL=redis://redis:6379/0
```

## Règles

- Ne pas utiliser `memory` en Kubernetes ou avec plusieurs workers.
- Définir un TTL pour chaque famille de clé.
- Préfixer les clés par service et environnement.
- Ne jamais cacher un secret en clair.
- Surveiller latence, erreurs Redis et taux de hit.

## Vérifier Localement

```bash
docker run --rm -d --name arclith-redis -p 6379:6379 redis:7-alpine
REDIS_URL=redis://127.0.0.1:6379/0 uv run pytest
docker stop arclith-redis
```

## Suite

Lire [secrets et Vault](secrets.md), puis la capability [cache/redis](../capabilities/cache.md).
