# Capability Repository

Persistance des entités métier derrière un port repository.

## Adapters

| Adapter | Usage |
|---|---|
| `memory` | tests, développement, smoke local |
| `mongodb` | standard document, single-tenant ou multitenant |
| `duckdb` | persistance fichier locale et analytique |
| `mariadb` | SQL serveur via SQLAlchemy async |

## Commande

```bash
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability repository --adapter mongodb --yes
```

## Configuration

```yaml
# config/adapters/adapters.yaml
repository: mongodb
```

## Règle

Un adapter inbound ne doit pas appeler `MongoDBRepository`, `DuckDBRepository` ou
`MariaDBRepository` directement. Il passe par un use case ou un port inbound.

## Validation

```bash
uv run pytest
```

## Suite

Lire [cache](cache.md) si plusieurs processus doivent partager l'état technique.
