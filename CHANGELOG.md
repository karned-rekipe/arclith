# Changelog

## [0.10.0] — 2026-08-03

### Added

- **Layout applicatif canonique** — `ProjectLayout`, `ProjectLayoutKind` et `canonical_project_layout()` exposent la
  convention `src/<package>/{domain,application,adapters,infrastructure}` pour les services Arclith.
- **Documentation de layout** — README et documentation d'architecture alignés sur le layout namespacé utilisé par
  `_sample`.

---

## [0.8.2] — 2026-04-04

### Fixed

- **`ws="websockets-sansio"`** — `Arclith.run_api()` et `ProbeServer.start_in_background()` forcent désormais l'implémentation sansio d'uvicorn. Corrige le `DeprecationWarning: websockets.legacy is deprecated` émis par `uvicorn 0.41.0` qui sélectionnait `websockets_impl.py` (legacy) dès que `websockets` était installé (via `fastmcp`).

---

## [0.8.0] — 2026-03-30

### Added

- **SOTA REST middlewares** — `CacheControlMiddleware`, `ETaggerMiddleware`, `IdempotencyMiddleware` (RFC 7231/7232/7234/7240/8288) auto-activés via `Arclith.fastapi()`
- **`config.http`** — section de config `HttpSettings` : `cache_control`, `etag`, `idempotency`
- **`client_id` dans `KeycloakSettings`** — client public PKCE pour Swagger UI, distinct de `audience` (validation JWT)

### Fixed

- **Swagger UI OAuth2 PKCE** — `_patch_openapi_keycloak` remplace `HTTPBearer` par `keycloak` dans la sécurité des routes et supprime `HTTPBearer` des `securitySchemes` → le dialog n'affiche que la section `keycloak (Authorized)`, sans champ vide confus
- **`initOAuth`** — utilise `client_id` (au lieu de `audience`), ajoute `prompt=login` pour forcer le formulaire Keycloak et éviter la reconnexion SSO silencieuse
- **`JWTDecoder`** — désactive `verify_aud` quand `audience=None` (PyJWT lève `InvalidAudienceError` même sans audience configurée si le token contient un claim `aud`)

---

## [0.7.1] — 2026-03-30

### Fixed

- **`load_config_dir` export** — ajout dans `__all__` (absent de PyPI 0.7.0, causait `ImportError` dans projets scaffoldés par `arclith-cli`)
- **`load_config_file` export** — ajout dans `__all__` pour compléter l'API publique
- **`export_config_yaml` export** — ajout dans `__all__` pour CLI `export-config`

---

## [0.7.0] — 2026-03-29

### Added

- **JWT auth pipeline** — `run_auth_pipeline()` in `adapters/inbound/auth_pipeline.py` : seule source de vérité pour la logique JWT (Bearer extraction → JWKS decode → licence → tenant resolution). Partagé par FastAPI et FastMCP.
- **`make_require_auth()`** — protection sélective opt-in des routes FastAPI (HTTPBearer → bouton Authorize Swagger). Exposé via `arclith.auth_dependency()`.
- **`make_require_auth_tool()`** — protection sélective opt-in des tools MCP. Exposé via `arclith.auth_dependency(transport="mcp")`.
- **Multitenant générique** — `TenantContext: dict[adapter_name → AdapterTenantCoords(params)]` : entièrement générique, sans hypothèse sur les clés (MongoDB, S3, MariaDB, Redis, …).
- **`JWTDecoder`** — validation JWKS Keycloak avec `CachePort` configurable (memory ou Redis).
- **`RoleLicenseValidator`** — vérification du rôle realm Keycloak depuis les claims JWT.
- **`MemoryCacheAdapter`** (zéro dépendance, défaut) + **`RedisCacheAdapter`** (`arclith[cache]`).
- **`make_inject_tenant_uri`** — accepte `list[TenantResolver]`, résout en parallèle, fusionne en un seul `TenantContext` par requête.
- **`VaultTenantResolver`** — résolution d'URI MongoDB (et autres) depuis HashiCorp Vault KV.
- **Swagger UI PKCE** — auto-configuré quand `config.keycloak` est présent dans `Arclith.fastapi()`.
- **`arclith.auth_dependency(transport)`** — factory unifiée retournant `require_auth` (FastAPI ou FastMCP) selon le transport.
- **`arclith._cache`** — `CachePort` partagé JWKS + résolutions tenant (memory ou Redis selon config).
- **`docs/auth.md`** — référence complète JWT : tous les patterns FastAPI + FastMCP, Swagger UI, contrôle par rôle, limitations.

### Changed

- **`fastapi/dependencies.py`** — wrapper FastAPI → `run_auth_pipeline()` (supprime le doublon `get_duration_ms`).
- **`fastmcp/dependencies.py`** — même signature que FastAPI, délègue à `run_auth_pipeline()`.
- **`multitenant` flag** — déplacé de `AdaptersSettings` vers `MongoDBSettings`/`DuckDBSettings`.
- **`auth_pipeline.py`** — helpers extraits pour réduire la complexité cyclomatique (C→A).
- **`config.py`** — suppression des doublons de classes (bug critique : `AppConfig.keycloak/tenant/license/cache` était écrasé).
- **Nouvelles sections config** : `KeycloakSettings`, `TenantSettings`, `LicenseSettings`, `CacheSettings`.

### Breaking Changes

- **`run_mcp_stdio()` supprimé** (ADR-007) — incompatible Kubernetes et auth JWT. Utiliser `run_mcp_http()` ou `run_mcp_sse()`.

---

## [0.6.1] — 2026-03-27

### Added

- **AppSettings.description** — New optional field in `app:` section of `config.yaml` for API description. Automatically injected into FastAPI Swagger/OpenAPI documentation via `arclith.fastapi()`. Default: `"API service built with arclith framework"`.

### Changed

- **FastAPI metadata injection** — `arclith.fastapi()` now automatically injects `title`, `version`, and `description` from `config.app.*` if not explicitly provided in kwargs. This enables centralized API metadata management through config.yaml.

---

## [0.6.0] — 2026-03-27

### Changed

- **request_id uses UUIDv7** — `ResponseMetadata.request_id` now uses UUIDv7 (time-ordered) instead of UUIDv4 for better traceability and chronological sorting. This aligns with the framework's `Entity.uuid` convention.

## [0.5.0] — 2026-03-26

### Added

- **ProbeServer** — Observabilité production-ready sur port dédié
  - `adapters/inbound/probes/server.py` : Starlette app isolée (daemon thread + asyncio loop)
  - Endpoints : `/health`, `/ready`, `/info`, `/metrics` (JSON)
  - `Arclith.add_readiness_check()` : health checks custom
  - `Arclith.run_with_probes(*runners, transports)` : orchestration multi-transport

- **Transport-aware Metrics** — Métriques par transport avec latencies (P50/P95/P99)
  - `adapters/inbound/probes/metrics.py` : `MetricsRegistry` (thread-safe)
  - `ApiMetricsCollector` : middleware Starlette ASGI (status/method/endpoint)
  - `McpMetricsCollector` : wrapper `FunctionTool.fn` (tool_name/success/error)
  - `EventBusCollectorProtocol` : Protocol pour futures implémentations
  - `Arclith.instrument_mcp(mcp)` : auto-attach metrics via `fastmcp._local_provider`
  - `Arclith.fastapi()` : auto-attach `ApiMetricsCollector` si `probe.enabled=true`

- **Pagination DB-native** — Single-query pagination avec count total
  - `Repository[T].find_page(offset, limit) -> tuple[list[T], int]`
  - Implémentation InMemory, MongoDB (`$facet`), DuckDB
  - `BaseService.find_page()` : use case paginé

- **Timing OTEL-ready** — Context manager pour mesurer la durée d'exécution
  - `log_duration(logger, operation, **ctx)` : context manager qui log la durée en ms
  - `TimingMiddleware` : FastAPI middleware qui injecte `duration_ms` dans les logs
  - `get_duration_ms()` : dependency FastAPI qui expose la durée de la requête

- **Configuration** — Nouvelles sections `app:` et `probe:` dans `config.yaml`
  - `AppSettings` : `name`, `version` (métadonnées app)
  - `ProbeSettings` : `host`, `port`, `enabled` (`:9000` par défaut)

### Breaking Changes

**Aucun** — Rétrocompatible avec 0.4.0. Le ProbeServer et les métriques sont opt-in.

---

## [0.4.0] — 2026-03-26

### Added

- **Standardized API Response Wrappers** — Richardson Maturity Model niveau 2-3 (HTTP + HATEOAS)
- `adapters/inbound/schemas/response_wrapper.py` : nouveaux schemas pour des réponses API cohérentes :
  - `ApiResponse[T]` : wrapper générique avec `status`, `data`, `error`, `metadata`
  - `PaginatedResponse[T]` : wrapper pour listes paginées avec `PaginationInfo`
  - `ResponseMetadata` : `request_id` (UUID v4), `timestamp` (UTC), `version`, `duration_ms`, `links` (HATEOAS)
  - `ErrorDetail` : erreurs structurées avec `type`, `message`, `field`
  - `PaginationInfo` : métadonnées de pagination (`total`, `page`, `per_page`, `has_next`, `has_prev`, etc.)
- **Factory functions** :
  - `success_response(data, metadata=None, links=None) -> ApiResponse[T]`
  - `error_response(error_type, message, field=None, metadata=None) -> ApiResponse[None]`
  - `paginated_response(data, total, page=1, per_page=20, ...) -> PaginatedResponse[T]`
- `adapters/inbound/schemas/__init__.py` : exports des nouveaux types et factories

### Standards

- Inspiré des APIs modernes (GitHub, Stripe, Twilio)
- Support des liens HATEOAS (autodécouvrabilité niveau 3 Richardson)
- Conformité HTTP stricte (ex: 204 No Content sans body)
- Traçabilité via `request_id` unique par requête

### Breaking Changes

**Aucun** — Cette release est **additive only**. Les wrappers sont disponibles mais optionnels pour les projets consommateurs.

---


### Added

- `domain/ports/secret_resolver.py` : port `SecretResolver` (ABC) — contrat pour tous les résolveurs de secrets.
- `infrastructure/secret_factory.py` : `build_secret_resolver()` — construit le résolveur depuis le dict de config brut (avant validation Pydantic). Supporte `vault`, `yaml`, `env`, `chain`.
- `infrastructure/secret_loader.py` : `resolve_dict_secrets()` — injecte les secrets dans le dict de config via leur chemin dot-notation avant la validation `AppConfig`.
- `adapters/outbound/vault/secret_adapter.py` : `VaultSecretAdapter` — lit depuis HashiCorp Vault KV v2. Token via `VAULT_TOKEN` ou `~/.vault-token`. Retourne `None` silencieusement si Vault est injoignable (fallback possible via chain).
- `adapters/outbound/yaml/secret_adapter.py` : `YamlSecretAdapter` — lit depuis un `secrets.yaml` gitignored (fallback dev local).
- `adapters/outbound/env/secret_adapter.py` : `EnvSecretAdapter` — lit depuis les variables d'environnement (`field.path` → `FIELD_PATH`).
- `adapters/outbound/chain/secret_adapter.py` : `ChainSecretAdapter` — tente chaque résolveur dans l'ordre, retourne la première valeur non-`None`.
- `infrastructure/config.py` : `SecretsSettings` (section `secrets:` dans `config.yaml`) + intégration dans `load_config()`.
- `pyproject.toml` : optional extra `vault = ["hvac>=2.3.0"]` ; `hvac` ajouté à l'extra `all`.
- `arclith/__init__.py` : `SecretResolver`, `build_secret_resolver`, `resolve_dict_secrets` exportés.

### Config `secrets:` dans `config.yaml`

```yaml
secrets:
  resolver: chain          # vault | yaml | env | chain
  chain: [vault, yaml]     # ordre de fallback pour chain
  mappings:
    adapters.mongodb.uri: rekipe/service/mongodb   # dot-path → clé Vault ou chemin yaml

  vault:
    addr: http://127.0.0.1:8200   # surchargeable via VAULT_ADDR
    mount: kv

  yaml:
    path: secrets.yaml   # relatif au répertoire du config.yaml
```

---

## [0.2.1] — 2026-03-18

### Fixed

- `DuckDBRepository._load` : `rel` est désormais enregistré via `con.register("rel", rel)` avant son utilisation dans la requête SQL — correction d'un bug potentiel de résolution de variable.
- `_UvicornLogInterceptHandler.emit` : utilise `traceback.format_exception(exc)` (signature Python 3.10+) à la place de `format_exception(*record.exc_info)`.
- `repository_factory` : assertions de vérification null ajoutées sur les configurations `mongodb` et `duckdb` avant utilisation.

### Changed

- `domain/ports/repository.py`, `domain/ports/logger.py` : méthodes abstraites annotées `# pragma: no cover`.
- `arclith/__init__.py` : ordonnancement des imports aligné ; `ConsoleLogger` réexporté pour les type checkers.
- `infrastructure/config.py` : `# nosec B104` sur le host par défaut `0.0.0.0`.

---

## [0.2.0] — 2026-03-18

### Breaking changes

- `Entity` migré de `@dataclass` vers `pydantic.BaseModel` (`model_copy`, `model_dump` remplacent `replace`, `asdict`).
- `MongoDBConfig` migré de `@dataclass` vers `pydantic.BaseModel` (frozen). Le champ `collection_name` devient optionnel et se place après `uri`.

### Added

- `Entity.coerce_uuid` : `field_validator` qui coerce `uuid.UUID` (stdlib) et `str` vers `uuid6.UUID` — corrige les erreurs de désérialisation DuckDB.
- `Entity` : `description` et `examples` sur tous les champs pour exposition OpenAPI / MCP.
- `DuckDBRepository` : création automatique du fichier de données au premier démarrage (CSV et JSON).
- `DuckDBRepository` : `path` peut être un répertoire — le nom de fichier est alors dérivé du nom de la classe entité.
- `MongoDBRepository` : `collection_name` dérivé automatiquement de `entity_class.__name__.lower()` si non fourni.
- `pytz` ajouté à l'extra `duckdb` (requis par DuckDB pour les timestamps avec timezone).

### Fixed

- `_UvicornLogInterceptHandler.emit()` : le traceback complet est désormais inclus dans les logs d'erreur ASGI.
- Suppression de `logging.root.handlers = [handler]` qui contaminait tous les loggers Python.
- Suppression du metadata `source` parasite sur les logs uvicorn.

### Changed

- `application/use_cases` (`create`, `update`, `delete`, `duplicate`) : `dataclasses.replace` remplacé par `model_copy`.
- `adapters/outbound` (memory, mongodb, duckdb) : `asdict`, `fields`, `replace` remplacés par les équivalents Pydantic.
- `MongoDBSettings` / `DuckDBSettings` dans `AppConfig` : `collection_name` optionnel, validator DuckDB accepte les répertoires.

---

## [0.1.0] — initial release
