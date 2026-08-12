# Baseline Production

Cette page donne la configuration de base à viser pour un service Arclith de production.

## Socle Minimal

| Besoin | Capability |
|---|---|
| API HTTP | [api/fastapi](../capabilities/api.md) |
| Auth JWT | [auth/keycloak](../capabilities/auth.md) |
| Licence par rôle | [license/role](../capabilities/license.md) |
| Secrets | [secrets/vault](../capabilities/secrets.md) ou [secrets/chain](../capabilities/secrets.md) |
| Cache partagé | [cache/redis](../capabilities/cache.md) |
| Repository | [repository/mongodb](../capabilities/repository.md) ou [repository/mariadb](../capabilities/repository.md) |
| Probes | [probe/server](../capabilities/probe.md) |
| Observabilité | [observability/opentelemetry](../capabilities/observability.md) |
| Runtime | [runtime/docker-image](../capabilities/runtime.md) |

## Parcours

1. [Auth production](auth.md)
2. [Cache production](cache.md)
3. [Secrets et Vault](secrets.md)
4. [Observabilité production](observability.md)
5. [Runtime et probes](runtime.md)

## Commandes De Départ

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli add-adapter --capability auth --adapter keycloak --yes
arclith-cli add-adapter --capability license --adapter role --yes
arclith-cli add-adapter --capability cache --adapter redis --yes
arclith-cli add-adapter --capability secrets --adapter chain \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/my-service/mongodb \
  --yes
arclith-cli add-adapter --capability probe --adapter server --yes
arclith-cli add-adapter --capability observability --adapter opentelemetry --yes
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
```

## Règles

- Aucun secret réel dans Git.
- `cache/redis` dès qu'il y a plusieurs workers, réplicas ou processus.
- `probe/server` obligatoire avant Docker ou Kubernetes.
- Les adapters inbound appellent les use cases, jamais les repositories concrets.
- L'image Docker reçoit les secrets au runtime, jamais au build.

## Validation

```bash
uv run pytest
make docs
docker build -t my-service:local .
```

## Suite

Lire les pages du parcours ci-dessus, puis [Docker Compose](../runtime-docker/docker-compose.md)
et [Kubernetes](../runtime-docker/kubernetes.md).
