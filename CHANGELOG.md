# Changelog

## [Unreleased]

### Added

- **Runtime OpenTelemetry optionnel de bout en bout** — contrats neutres pour runtime, métriques,
  corrélation, propagation et logs; providers `managed`/`attach`/`external`; traces, métriques,
  logs OTLP, batch/flush/shutdown, diagnostics et escape hatch natif.
- **Instrumentations OpenTelemetry** — FastAPI, HTTPX, FastMCP expérimental versionné, RabbitMQ,
  Pydantic AI/LangGraph, repositories et caches, avec propagation W3C et cardinalité bornée.
- **Profils CLI OpenTelemetry** — profils `development` et `production`, YAML imbriqué,
  `.env.example` sans secret et ajout idempotent de `arclith[opentelemetry]`.
- **Persistance agent LangGraph** — capability optionnelle `agent-persistence`, configuration
  checkpointer/store, registry custom, wiring embedded/Agent Server et extras SQLite, PostgreSQL,
  MongoDB et Redis granulaires.
- **Runtime LangSmith optionnel** — port `TracePort` provider-neutral, tracer no-op, configuration
  programmatique du client, contexte conditionnel, sampling, confidentialité, propagation
  FastAPI/FastMCP/RabbitMQ, cycle de vie flush/close et escape hatch `langsmith_client()`.
- **Instrumentation agents** — `Arclith.langgraph()` initialise le contexte LangSmith et
  `Arclith.pydantic_ai_llm()` injecte l'instrumentation OpenTelemetry dans les seuls agents Pydantic
  AI construits par Arclith.
- **Profils CLI LangSmith** — profils `development` et `production`, génération de `.env.example`
  sans secret et ajout idempotent de l'extra `arclith[langsmith]`.

### Changed

- **Composition d'observabilité neutre** — `Arclith` pilote désormais un unique
  `ObservabilityRuntimePort`; le logger console et RabbitMQ n'importent plus OpenTelemetry.
- **Extra OpenTelemetry** — l'instrumentation HTTPX rejoint l'extra optionnel; la corrélation des
  logs n'installe plus de handler/root logger global.
- **Extra LangSmith dédié** — `langsmith[otel]>=0.10,<1` quitte la déclaration directe de l'extra
  `langgraph`. Les projets utilisant explicitement LangSmith doivent ajouter
  `arclith[langsmith]`; `arclith[all]` continue de l'inclure.
- **Coexistence OpenTelemetry** — lorsque les deux adapters sont actifs, LangSmith utilise
  obligatoirement le mode `otel` et ajoute un processor au provider partagé afin d'éviter les spans
  dupliqués.

### Security

- **Télémétrie privacy-safe** — pas de payload, corps HTTP, contenu GenAI, clé de cache, entité,
  UUID ou header implicite; baggage allowlisté et diagnostics sans valeur de secret.
- **Capture sûre par défaut** — inputs, outputs, prompts, réponses, binaires et paramètres modèle
  sont masqués; le baggage est vide sans allowlist et la CLI refuse toute clé LangSmith en argument.

---

## [0.18.0] — 2026-08-25

### Added

- **Adapter repository PostgreSQL** — extra optionnel `arclith[postgresql]`, settings
  `adapters.postgresql`, factory par defaut et repository generique JSONB par entite.
- **Scaffold CLI PostgreSQL** — `arclith-cli add-adapter --capability repository --adapter
  postgresql` genere la configuration et le wiring d'un repository PostgreSQL.

### Changed

- **Versions release** — `arclith` passe à `0.18.0`; `arclith-cli` passe à `0.15.0`
  et dépend de `arclith>=0.18.0`.

### Fixed

- **Schemas PostgreSQL custom** — l'adapter cree idempotemment les schemas non-public avant
  `metadata.create_all()`, y compris pour les coordonnees multitenant.

---

## [0.17.0] — 2026-08-23

### Added

- **Streaming structuré LLM** — `LLMPort.stream_structured()` expose des événements provider-neutral
  `progress`, `structured_chunk` et `structured_final`, avec options de progression, snapshots et
  debounce.
- **PydanticAI streaming** — l'adapter PydanticAI utilise `Agent.run_stream()` et `stream_output()`
  pour émettre des snapshots structurés cumulés avant l'objet final.
- **LangGraph progress configurable** — `LangGraphSettings.stream_mode` et
  `Arclith.langgraph(..., stream_mode=...)` configurent les modes `values`, `updates`, `custom`,
  `messages`, `checkpoints`, `tasks` ou `debug`.
- **Scaffold CLI LangGraph** — `arclith-cli add-adapter --capability agent --adapter langgraph`
  accepte `--param stream_mode=...` et génère un événement `custom` minimal via `get_stream_writer()`.

### Changed

- **Versions release** — `arclith` passe à `0.17.0`; `arclith-cli` passe à `0.14.0`
  et dépend de `arclith>=0.17.0`.

### Fixed

- **Payloads de streaming JSON-friendly** — `llm_stream_event_to_payload()` sérialise récursivement
  les sorties et métadonnées pour éviter de publier des objets Python non encodables.

---

## [0.16.0] — 2026-08-12

### Added

- **Capabilities `arclith-cli` complètes** — le catalogue expose maintenant les adapters standardisés
  pour repository memory/MongoDB/DuckDB/MariaDB, API FastAPI, MCP FastMCP, LLM LM Studio/OpenAI/
  Anthropic, agent LangGraph, observabilité LangSmith/OpenTelemetry, cache memory/Redis, auth
  Keycloak, secrets env/YAML/Vault/chain, tenant Vault, licence par rôle, logger console, probes,
  middlewares HTTP, command bus RabbitMQ et runtime Docker.
- **Command bus RabbitMQ** — extra `arclith[rabbitmq]`, settings `command_bus`, publisher et worker
  avec ack manuel, publisher confirms, prefetch/concurrency bornés, DLX/retry et propagation
  `correlation_id`/`traceparent`.
- **Runtime Docker** — adapter `runtime/docker-image` générant `Dockerfile`, `.dockerignore` et
  `arclith-run` pour une image Python 3.13 multi-stage, non-root, configurable au runtime pour API,
  MCP, bus, agent ou mode combiné.
- **OpenTelemetry OTLP** — configuration et adapter de traces/metrics OTLP avec corrélation
  `trace_id`/`span_id` et instrumentation FastAPI/logging.
- **Tutoriel Todo complet** — walkthrough POC-source-faithful couvrant API, MCP, agent LangGraph,
  MongoDB partagé, LangSmith et Jaeger.

### Changed

- **Versions release** — `arclith` passe à `0.16.0`; `arclith-cli` passe à `0.13.0`
  et dépend de `arclith>=0.16.0`.

### Fixed

- **MongoDB dates** — sérialisation correcte des champs `date` dans l'adapter MongoDB.
- **Docs MkDocs** — rendu des blocs de code stabilisé.

---

## [0.15.0] — 2026-08-07

### Changed

- **Intent interpreter** — le scaffold applicatif expose `add-intent-interpreter` et le dossier
  `application/intent_interpreters`, pour nommer explicitement la traduction d'intention avant
  l'appel des use cases.
- **Versions LM Studio** — `arclith` passe à `0.15.0`; `arclith-cli` passe à `0.12.0`
  et dépend de `arclith>=0.15.0`.

### Fixed

- **Structured output LM Studio** — les modèles OpenAI-compatibles utilisent un profil de sortie
  structurée compatible `json_schema`, afin de fonctionner avec LM Studio tout en conservant les
  chemins OpenAI et Anthropic.

---

## [0.14.0] — 2026-08-07

### Changed

- **Observability cumulative** — `adapters.observability` devient une configuration structurée
  `observability.enabled`, pour activer `langsmith` et `opentelemetry` en parallèle. L'ancien
  format scalaire `observability: langsmith|opentelemetry|none` n'est plus accepté, et
  `opentelemetry.yaml` ne contient plus de flag `enabled`.
- **Versions observability** — `arclith` passe à `0.14.0`; `arclith-cli` passe à `0.11.0`
  et dépend de `arclith>=0.14.0`, afin que les projets générés utilisent le même schéma de
  configuration que le tutoriel.

---

## [0.13.0] — 2026-08-06

### Added

- **Scaffold du cœur métier** — `arclith-cli add-entity` et `arclith-cli add-usecase`
  créent les fichiers minimaux sans générer de CRUD, d'adapter ou de wiring implicite.
- **Documentation de release** — ajout d'une procédure de publication PyPI avec les Trusted
  Publishers attendus pour `arclith` et `arclith-cli`.

### Changed

- **Publication PyPI séparée** — le workflow publie `arclith` et `arclith-cli` dans deux jobs
  OIDC distincts, chacun rattaché à son environnement PyPI.
- **Versions release** — `arclith` passe à `0.13.0`; `arclith-cli` passe à `0.10.0` et dépend
  de `arclith>=0.13.0`.

---

## [0.12.0] — 2026-08-06

### Added

- **Extra `arclith[langgraph]` publié** — installe LangGraph, LangGraph CLI/API, LangSmith et
  PydanticAI OpenAI/Anthropic pour les projets agents.
- **Publication `arclith-cli`** — le workflow PyPI publie maintenant le framework et la CLI depuis
  le même tag release.

### Changed

- **Extra agent renommé** — `arclith[langgraph]` remplace l'ancien extra public `arclith[agent]`
  pour aligner la dépendance optionnelle avec le runtime produit.
- **Version CLI** — `arclith-cli` passe à `0.9.0` et dépend de `arclith>=0.12.0`.
- **Extra auth** — `PyJWT[crypto]` remplace `PyJWT[cryptography]` dans `arclith[auth]` et
  `arclith[all]`, conformément aux métadonnées PyJWT actuelles.

---

## [0.11.0] — 2026-08-04

### Added

- **Adapter repository MariaDB** — extra optionnel `arclith[mariadb]`, settings `adapters.mariadb`, factory par defaut et repository generique JSON par entite.
- **Parametres CLI generiques** — `arclith-cli add-adapter --param key=value` permet d'ajouter des adapters sans creer une option CLI specialisee par champ.

### Changed

- **Rupture nette pre-1.0** — suppression des chemins de normalisation `input`/`output` vers `inbound`/`outbound`; le template officiel doit deja respecter le layout canonique.
- **Config explicite** — suppression de `load_config()`; utiliser `load_config_dir()` ou `load_config_file()` selon le format attendu.

### Fixed

- **MariaDB multitenant** — `adapters.mariadb` peut etre valide sans `url` ni `database` quand `multitenant=true`; les coordonnees viennent du contexte tenant.
- **Parametres adapter CLI** — les `--param key=value` inconnus sont rejetes meme pour les adapters sans parametre catalogue.
- **MariaDB tenant params** — le port tenant est trimme et borne a `1..65535`; les mots de passe sont preserves dans `with_tenant_params()`.
- **Quickstart scaffold** — le premier `uv sync` n'utilise plus `--frozen`, car `arclith-cli` supprime volontairement `uv.lock` dans les projets generes.

---

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
