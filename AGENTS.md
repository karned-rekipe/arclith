# AGENTS.md — Arclith (`arclith`)

## Contexte global

`arclith` est le framework hexagonal partagé par les microservices Arclith/Rekipe. Il est publié sur PyPI (`arclith>=0.2.0`) et
ne doit contenir aucune logique métier. Les repos consommateurs (`recipe/`, `_sample/`) l'importent en dépendance.

## Rôle

Fournir les primitives réutilisables pour construire des services en architecture hexagonale :

- Modèle de base `Entity` (UUIDv7, audit, soft-delete, optimistic locking)
- Port `Repository[T]` (CRUD async + `find_deleted` + `duplicate`)
- `BaseService[T]` qui câble les use cases standards
- `Arclith` : bootstrap, config, FastAPI, FastMCP, Uvicorn
- Trois implémentations de `Repository` : memory, MongoDB (motor), DuckDB

## Règles de développement

- **Pas d'import applicatif** dans `arclith/` — zéro référence à un domaine métier.
- `domain/` n'importe que `pydantic` et `uuid6`.
- Tout nouveau adaptateur doit être branché dans `build_repository()`.
- Dépendances groupées : installer uniquement ce qui est nécessaire (`[mongodb]`, `[duckdb]`, `[fastapi]`, `[mcp]`,
  `[all]`).
- Coverage **≥ 90 %** : `make coverage`.
- Pre-commit gate : `make precommit` (lint + typecheck + security).
- **HTTP Status Codes** : toujours déclarer explicitement `status_code` et `responses` dans FastAPI. Voir `docs/http-conventions.md`.

## Architecture

```
arclith/
  domain/
    models/entity.py          # Entity (UUIDv7, audit, soft-delete, version)
    models/tenant.py          # TenantContext + AdapterTenantCoords
    ports/repository.py       # Repository[T] (ABC, CRUD + find_deleted + duplicate)
    ports/logger.py           # Logger (ABC)
    ports/cache.py            # CachePort (ABC)
    ports/license_validator.py # LicenseValidator (ABC)
    ports/tenant_resolver.py  # TenantResolver (ABC)
  application/
    use_cases/                # CreateUseCase, ReadUseCase, UpdateUseCase, DeleteUseCase,
                              # FindAllUseCase, DuplicateUseCase, PurgeUseCase
    services/base_service.py  # BaseService[T] — câble les 7 use cases
  adapters/
    context.py                # set_tenant_context / get_tenant_context (ContextVar multitenant)
    input/
      auth_pipeline.py        # run_auth_pipeline() — pipeline JWT mutualisé (transport-agnostique)
      fastapi/
        dependencies.py       # make_inject_tenant_uri() — wrapper FastAPI → run_auth_pipeline
        auth.py               # make_require_auth() — protection sélective opt-in
        timing.py             # TimingMiddleware
      fastmcp/
        dependencies.py       # make_inject_tenant_uri() — wrapper FastMCP → run_auth_pipeline
        auth.py               # make_require_auth_tool() — protection sélective opt-in
      jwt/decoder.py          # JWTDecoder — valide JWT via JWKS Keycloak (cache)
      license/validator.py    # RoleLicenseValidator — vérifie realm role
    output/
      memory/repository.py    # InMemoryRepository[T]
      memory/cache_adapter.py # MemoryCacheAdapter
      mongodb/repository.py   # MongoDBRepository[T] (motor)
      duckdb/repository.py    # DuckDBRepository[T]
      redis/cache_adapter.py  # RedisCacheAdapter
      vault/tenant_adapter.py # VaultTenantResolver
      console/logger.py       # ConsoleLogger (loguru)
  infrastructure/
    config.py                 # AppConfig + load_config() — valide config.yaml
    repository_factory.py     # build_repository(config, entity_class, logger)
  arclith.py                  # Arclith — point d'entrée unique
```

### Flux de données

```
config.yaml → load_config() → AppConfig
Arclith.__init__(config_path)
  └─ .repository(entity_class) → build_repository() → InMemory|MongoDB|DuckDB Repository
  └─ .fastapi(**kwargs) → FastAPI avec lifespan
  └─ .fastmcp(name) → FastMCP
  └─ .run_api() / .run_mcp_sse() / .run_mcp_http()
```

## Primitives détaillées

### `Entity` (`domain/models/entity.py`)

| Champ                       | Type               | Description                        |
|-----------------------------|--------------------|------------------------------------|
| `uuid`                      | `UUID` (v7)        | ID time-ordered, auto-généré       |
| `created_at` / `updated_at` | `datetime` UTC     | Audit temporel                     |
| `created_by` / `updated_by` | `str \| None`      | Audit acteur                       |
| `deleted_at` / `deleted_by` | `datetime \| None` | Soft-delete                        |
| `version`                   | `int` (défaut 1)   | Optimistic locking                 |
| `is_deleted`                | property           | `True` si `deleted_at is not None` |

### `Repository[T]` (`domain/ports/repository.py`)

Méthodes abstraites : `create`, `read`, `update`, `delete`, `find_all`, `find_deleted`, `duplicate`.

### `BaseService[T]` (`application/services/base_service.py`)

Constructeur : `__init__(repository, logger, retention_days=None)`.  
Méthodes publiques : `create`, `read`, `update`, `delete`, `find_all`, `duplicate`, `purge`.

### `Arclith` (`arclith.py`)

| Méthode                     | Retour          | Usage                              |
|-----------------------------|-----------------|------------------------------------|
| `.repository(entity_class)` | `Repository[T]` | Instancie via `build_repository()` |
| `.fastapi(**kwargs)`        | `FastAPI`       | Crée l'app avec lifespan + OAuth2 Swagger si keycloak configuré |
| `.fastmcp(name)`            | `FastMCP`       | Crée le serveur MCP                |
| `.auth_dependency(transport)` | `Callable`    | Retourne `require_auth` (FastAPI ou FastMCP) depuis la config |
| `.run_api(app)`             | —               | Lance Uvicorn (config `api:`)      |
| `.run_mcp_sse(mcp)`         | —               | Transport SSE (config `mcp:`)      |
| `.run_mcp_http(mcp)`        | —               | Transport streamable-HTTP          |
| `._cache`                   | `CachePort`     | Cache partagé JWKS + tenant (memory ou Redis selon config) |

> ⚠️ `run_mcp_stdio()` est **supprimé** (ADR-007) — incompatible Kubernetes et auth JWT.

### `AppConfig` (`infrastructure/config.py`)

Sections validées depuis `config.yaml` :

| Section       | Clés notables                                                                                        |
|---------------|------------------------------------------------------------------------------------------------------|
| `adapters`    | `repository` (memory/mongodb/duckdb), `multitenant`, `mongodb.uri`, `mongodb.db_name`, `duckdb.path` |
| `api`         | `host`, `port`, `reload`                                                                             |
| `mcp`         | `host`, `port`                                                                                       |
| `soft_delete` | `retention_days` (None = ∞, 0 = immédiat)                                                            |

## Conventions

- Nommage adaptateurs output : `InMemory<Entity>Repository`, `MongoDB<Entity>Repository`, `DuckDB<Entity>Repository`.
- Logger injecté partout — jamais `print()` ni `logging` directement dans les use cases.
- `PurgeUseCase` : supprime physiquement les entités dont `deleted_at` est dépassé de `retention_days` jours.

## Commandes utiles

```bash
make setup       # uv sync --group dev --extra all
make precommit   # lint + typecheck + security
make quality     # lint + security + complexity + typecheck + coverage (≥90 %)
make test        # pytest -v
```

## Fichiers à lire en premier

1. `arclith/domain/models/entity.py` — comprendre la base de toute entité
2. `arclith/domain/ports/repository.py` — le contrat de persistance
3. `arclith/application/services/base_service.py` — les use cases câblés
4. `arclith/infrastructure/config.py` — la config validée
5. `arclith/infrastructure/repository_factory.py` — le routage des implémentations
6. `docs/http-conventions.md` — status codes HTTP/REST SOTA
7. `docs/auth.md` — authentification JWT : tous les patterns FastAPI + FastMCP
8. `docs/multitenant.md` — isolation multi-tenant via Vault + ContextVar
