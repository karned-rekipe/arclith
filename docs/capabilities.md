# Capacités standardisées

Arclith doit fournir une base stable pour assembler rapidement des services hexagonaux. La CLI
s'appuie donc sur un catalogue de capacités plutôt que sur des chemins codés au cas par cas.

## Principe

Une capacité décrit:

- le rôle architectural exposé par la CLI;
- le layer hexagonal concerne, `inbound` ou `outbound`;
- les adapters disponibles;
- les paramètres requis par adapter;
- le chemin de configuration;
- la clé d'activation dans `config/adapters/adapters.yaml`, quand la capacité a besoin d'un
  sélecteur actif.

Le code métier reste dans `domain/` et `application/`. Les capacités ne doivent générer que du
câblage, des ports, des schémas ou des adapters autour de ce cœur.

## Scaffold du cœur métier

`arclith-cli init` initialise un projet vide de métier. Les entités et les use cases ne sont pas des capacités du catalogue : ils appartiennent au cœur
métier. La CLI peut seulement poser les fichiers minimaux, sans CRUD par défaut et sans câblage
automatique vers FastAPI, FastMCP, LangGraph ou un repository.

```bash
arclith-cli init todo-list-service
cd todo-list-service
arclith-cli add-entity ShoppingItem
arclith-cli add-usecase PlanShoppingList
arclith-cli add-intent-interpreter ShoppingIntent
```

Fichiers générés :

```text
src/<package>/domain/models/shopping_item.py
src/<package>/domain/ports/inbound/plan_shopping_list.py
src/<package>/application/use_cases/plan_shopping_list.py
src/<package>/application/intent_interpreters/shopping_intent.py
```

Le développeur garde la responsabilité de définir les champs, invariants et orchestration métier.
Les adapters se branchent ensuite explicitement via `add-adapter` et appellent les ports inbound.

## Catalogue actuel

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

### `repository`

Capacité outbound pour la persistance des entités métier derrière un port repository.

Adaptateurs disponibles:

- `memory`: stockage volatile pour dev, tests et smoke locaux;
- `mongodb`: repository async MongoDB, single-tenant ou multitenant;
- `duckdb`: repository fichier local pour SQL analytique et démos sans serveur;
- `mariadb`: repository MariaDB async optionnel, avec stockage générique JSON par entité.

`memory` reste le chemin zéro dépendance pour les tests, les use cases et les smokes locaux. Il
n'ajoute aucun fichier de configuration dédié: l'activation se limite à `repository: memory`. Chaque
processus Python possède son propre stockage mémoire; une API, un serveur MCP et un agent lancés
séparément ne partagent donc pas leur état. Utiliser un repository persistant pour les scénarios
multi-processus.

`mongodb` est le choix standard quand plusieurs processus doivent partager le même état, par exemple
API, MCP et agent LangGraph. La CLI génère `config/adapters/outbound/mongodb.yaml` et mappe
`adapters.mongodb.uri` vers `MONGODB_URI` dans `config/secrets.yaml` avec le resolver `env`. L'URI
réelle reste hors Git: exporter `MONGODB_URI`, remplacer le resolver par `vault`, ou utiliser un
resolver `chain` selon l'environnement.

Single-tenant:

```yaml
# config/adapters/adapters.yaml
repository: mongodb

# config/adapters/outbound/mongodb.yaml
uri: null
db_name: my_service
collection_name: null
multitenant: false
```

Multitenant:

```yaml
# config/adapters/outbound/mongodb.yaml
uri: null
db_name: fallback_db
collection_name: null
multitenant: true
```

En multitenant, `VaultTenantResolver` fournit `uri` et peut fournir `db_name` pour la requête
courante. `db_name` reste un fallback si le secret tenant ne le porte pas.

Activation:

```yaml
repository: mongodb
```

`duckdb` est adapté aux développements locaux, tests d'intégration légers et démonstrations
analytiques qui ont besoin d'un état durable sans serveur MongoDB. La CLI génère
`config/adapters/outbound/duckdb.yaml` avec un chemin local explicite; `data/` est le défaut
compatible avec un projet généré.

Préférer `memory` pour les tests unitaires et smokes sans persistance. Préférer `mongodb` quand
plusieurs processus ou canaux Arclith doivent partager le même état, par exemple API, MCP et agent
LangGraph. DuckDB couvre l'entre-deux local: persistance fichier, SQL analytique et setup
zéro service.

Formats DuckDB acceptés par `DuckDBSettings`: dossier explicite avec `/`, `.csv`, `.parquet`,
`.json` ou `.arrow`.

```yaml
# config/adapters/adapters.yaml
repository: duckdb

# config/adapters/outbound/duckdb.yaml
multitenant: false
path: data/
```

`mariadb` est l'option SQL serveur. Il reste un adapter repository optionnel: installer
`arclith[mariadb]` uniquement dans les services qui l'utilisent. Le package de base et les tests
sans extra ne doivent pas importer SQLAlchemy ou `asyncmy`.

La CLI génère la configuration non secrète dans `config/adapters/outbound/mariadb.yaml` et ajoute
les mappings secrets dans `config/secrets.yaml`. Ne pas passer ni écrire de mot de passe réel dans
`mariadb.yaml`; utiliser `MARIADB_PASSWORD` ou `MARIADB_URL`, ou remplacer le resolver `env` par
`vault` selon l'environnement.

```yaml
# config/adapters/adapters.yaml
repository: mariadb

# config/adapters/outbound/mariadb.yaml
url: null
host: 127.0.0.1
port: 3306
database: my_service
user: app
password: null
driver: asyncmy
table_prefix: ""
multitenant: false

# config/secrets.yaml
resolver: env
mappings:
  adapters.mariadb.url: MARIADB_URL
  adapters.mariadb.password: MARIADB_PASSWORD
```

En single-tenant, `database` est requis quand `url` n'est pas fourni par les secrets. En
multitenant, le contexte tenant peut fournir `url`, `database`, `user`, `password`, `host`, `port`,
`driver` ou `table_prefix`.

### `logger`

Capacité outbound pour le logger applicatif partagé par les use cases et les adapters. L'adapter
actuel reste volontairement unique: `console`. Il est explicite dans le catalogue pour garder le
contrat remplaçable plus tard sans changer les ports applicatifs.

Adapter disponible:

- `console`: logger Loguru vers `stderr`, derrière le port `Logger`.

```bash
arclith-cli add-adapter \
  --capability logger \
  --adapter console \
  --yes
```

Résultat:

```yaml
# config/adapters/adapters.yaml
logger: console
```

`Arclith.logger` respecte `config.adapters.logger`; toute valeur inconnue est rejetée avec la liste
des adapters supportés. Le format console actuel est:

```text
YYYY-MM-DD HH:mm:ss | <emoji> <LEVEL> | <message> | <metadata>
```

Quand OpenTelemetry est actif et qu'un span courant existe, `ConsoleLogger` ajoute `trace_id`,
`span_id` et `trace_sampled` aux métadonnées. Le logger console ne fournit pas encore de sortie JSON,
de rotation ou d'export externe: ces variantes devront être ajoutées comme nouveaux adapters du même
catalogue.

### `cache`

Capacité outbound transverse pour le cache technique utilisé par JWT JWKS, idempotency et
résolution tenant. Elle n'est pas liée aux entités métier et ne doit pas être confondue avec
`repository/memory`, qui stocke les entités derrière un port repository.

Adaptateurs disponibles:

- `memory`: cache local par processus pour développement, tests, smokes locaux et worker unique.
- `redis`: cache partagé pour workers multiples, réplicas Kubernetes ou processus API/MCP/agent
  séparés.

Configuration runtime:

```yaml
# config/adapters/inbound/cache.yaml
backend: memory
jwks_ttl: 3600
tenant_uri_ttl: 300
```

Redis:

```yaml
# config/adapters/inbound/cache.yaml
backend: redis
redis_url: ""
jwks_ttl: 3600
tenant_uri_ttl: 300

# config/secrets.yaml
resolver: env
mappings:
  cache.redis_url: REDIS_URL
```

Cette capacité n'a pas de clé d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/inbound/cache.yaml` est chargé directement dans `AppConfig.cache`.

`memory` garde les entrées uniquement dans le processus Python courant. Une API, un serveur MCP, un
agent LangGraph ou plusieurs workers lancés séparément ne partagent donc pas les JWKS, réponses
idempotentes ou coordonnées tenant mises en cache. Passer à Redis dès qu'il faut un cache partagé
entre workers, réplicas ou processus API/MCP/agent.

Installer l'extra Redis dans les services qui activent `cache/redis`:

```bash
uv add "arclith[cache]"
```

Exemple Docker Compose local:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

Depuis un service lancé dans le même réseau Compose, utiliser `REDIS_URL=redis://redis:6379`. Depuis
un processus lancé sur l'hôte, utiliser `REDIS_URL=redis://127.0.0.1:6379`.

### `secrets`

Capacité outbound transverse pour résoudre les secrets avant validation Pydantic de `AppConfig`.
Elle ne génère jamais de valeur réelle: elle ne déclare que le resolver et les mappings dans
`config/secrets.yaml`.

Adaptateurs disponibles:

- `env`: lit les valeurs depuis les variables d'environnement du processus, compatible Docker,
  Kubernetes, CI/CD et plateformes cloud.
- `yaml`: lit un fichier YAML local gitignoré pour POC et développement sans Vault.

Ajouter un mapping avec une clé explicite:

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter env \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=MONGODB_URI \
  --yes
```

Résultat:

```yaml
# config/secrets.yaml
resolver: env
mappings:
  adapters.mongodb.uri: MONGODB_URI
```

Ajouter un mapping avec un nom dérivé:

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter env \
  --param field_path=adapters.mongodb.uri \
  --yes
```

Dans ce cas, la valeur du mapping reste vide et `EnvSecretAdapter` dérive le nom d'environnement
depuis le chemin de champ: `adapters.mongodb.uri` devient `ADAPTERS_MONGODB_URI`. Une clé explicite
prime toujours sur le nom dérivé, ce qui permet de garder les conventions d'écosystème comme
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MONGODB_URI`, `MARIADB_URL` ou `REDIS_URL`.

`arclith-cli` fusionne les nouveaux mappings dans `config/secrets.yaml` sans supprimer les mappings
existants. Si un secret requis manque et que le champ cible n'est pas explicitement `null`, le
chargement de configuration échoue avec un message `Secrets non résolus` qui liste le champ concerné.

Pour un fallback local, utiliser `secrets/yaml` :

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter yaml \
  --param field_path=adapters.mongodb.uri \
  --param path=secrets.yaml \
  --yes
```

Résultat côté configuration:

```yaml
# config/secrets.yaml
resolver: yaml
yaml:
  path: secrets.yaml
mappings:
  adapters.mongodb.uri: ""
```

Le CLI génère aussi `secrets.yaml.template` sans valeur réelle et ajoute `secrets.yaml` à
`.gitignore`. Copier le template localement puis renseigner la valeur sensible dans le fichier
ignoré:

```yaml
# secrets.yaml
adapters:
  mongodb:
    uri: mongodb://localhost:27017/my_service
```

Le fichier local suit le format imbriqué du `field_path`: `adapters.mongodb.uri` devient
`adapters -> mongodb -> uri`. Le resolver YAML ignore la clé descriptive du mapping et lit toujours
le chemin imbriqué, ce qui évite de stocker des secrets sous des noms plats non typés.

Pour Vault KV v2, installer l'extra dans le service qui charge la configuration :

```bash
uv add "arclith[vault]"
```

Puis configurer le resolver sans token :

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter vault \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/demo/mongodb \
  --param addr=http://vault:8200 \
  --param mount=kv \
  --yes
```

Résultat:

```yaml
# config/secrets.yaml
resolver: vault
vault:
  addr: http://vault:8200
  mount: kv
mappings:
  adapters.mongodb.uri: apps/demo/mongodb
```

Le token Vault n'est jamais écrit par la CLI. Au runtime, `VaultSecretAdapter` lit `VAULT_TOKEN` ou
`~/.vault-token`. `VAULT_ADDR` peut surcharger `secrets.vault.addr`, ce qui permet de garder le même
fichier de configuration entre local, CI et cluster.

POC local minimal :

```bash
vault server -dev
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=<root-token-dev>
vault secrets enable -path=kv -version=2 kv
vault kv put kv/apps/demo/mongodb value="mongodb://localhost:27017/demo"
```

Le mount `kv` doit être un engine KV v2. Avec `hvac`, Arclith lit le secret via KV v2 avec
`mount_point=kv` et attend la valeur applicative dans le champ `value`. Pour une policy dédiée, le
chemin de lecture Vault correspondant est `kv/data/apps/demo/mongodb`.

Pour combiner plusieurs environnements, utiliser `secrets/chain`. L'ordre est explicite et le
premier resolver qui retourne une valeur gagne:

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter chain \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/demo/mongodb \
  --param resolvers=env,vault,yaml \
  --param addr=http://vault:8200 \
  --param mount=kv \
  --param path=secrets.yaml \
  --yes
```

Résultat:

```yaml
# config/secrets.yaml
resolver: chain
chain:
  - env
  - vault
  - yaml
vault:
  addr: http://vault:8200
  mount: kv
yaml:
  path: secrets.yaml
mappings:
  adapters.mongodb.uri: apps/demo/mongodb
```

Profils recommandés:

- local POC: `yaml`, ou `chain` avec `env,yaml` pour permettre une surcharge ponctuelle;
- CI/CD et plateformes cloud: `env`, injecté par le système de déploiement;
- production avec secret manager: `vault`, ou `chain` avec `env,vault` si certains secrets sont
  injectés par la plateforme.

La CLI refuse les noms inconnus dans `resolvers`; les valeurs supportées sont `env`, `vault` et
`yaml`. Si aucun resolver ne trouve la valeur et que le champ cible n'est pas explicitement `null`,
le chargement échoue toujours avec `Secrets non résolus` et le champ manquant.

### `api`

Capacité inbound pour exposer les cas d'usage via HTTP REST.

Adapter disponible:

- `fastapi`: application FastAPI configurée par `Arclith.fastapi()`.

Configuration runtime:

```yaml
# config/adapters/inbound/fastapi.yaml
host: 0.0.0.0
port: 8000
reload: true
```

Cette capacité n'a pas de clé d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/inbound/fastapi.yaml` est chargé directement dans `AppConfig.api`.

La CLI configure uniquement le runtime FastAPI. Les routers métier restent dans le projet généré et
doivent traduire HTTP vers les ports inbound ou les use cases applicatifs, jamais vers un repository
concret. Le branchement attendu est donc:

```python
from arclith import Arclith
from my_service.adapters.inbound.fastapi.routes import router

arclith = Arclith("config")
app = arclith.fastapi()
app.include_router(router)
```

Le module `routes` appartient au projet consommateur: il construit ou injecte ses use cases, puis
appelle les ports applicatifs. `arclith-cli add-adapter --capability api --adapter fastapi` ne
génère pas ces routes pour éviter de mélanger transport HTTP et logique métier.

### `http`

Capacité inbound pour configurer les middlewares HTTP transverses de `Arclith.fastapi()` sans
modifier les routes métier.

Adapter disponible:

- `idempotency`: middleware `Idempotency-Key` pour éviter les doubles mutations `POST`.
- `etag`: middleware `ETag` / `If-None-Match` pour les lectures `GET` cacheables.
- `cache-control`: directives `Cache-Control` pour lectures `GET` et mutations.

```bash
arclith-cli add-adapter \
  --capability http \
  --adapter idempotency \
  --param enabled=true \
  --param ttl_seconds=86400 \
  --param required=false \
  --yes
```

Résultat fusionné dans `config/http.yaml` sans écraser `etag` ni `cache_control`:

```yaml
idempotency:
  enabled: true
  ttl_seconds: 86400
  required: false
```

Quand `enabled: true`, `Arclith.fastapi()` ajoute `IdempotencyMiddleware`. Le client fournit
`Idempotency-Key` sur les `POST`; au premier succès `2xx`, la réponse est stockée dans le cache
technique pendant `ttl_seconds`. Une requête suivante avec la même clé et le même path rejoue la
réponse stockée avec `X-Idempotency-Replay: true`. Les réponses `4xx` et `5xx` ne sont pas mises en
cache. Avec `required: true`, un `POST` sans header est rejeté en `400`.

Le cache sous-jacent est `cache/memory` par défaut: il suffit en développement ou mono-processus.
En multi-worker, Kubernetes ou API/MCP séparés, configurer `cache/redis` pour partager les clés
idempotentes entre processus.

```bash
arclith-cli add-adapter \
  --capability http \
  --adapter etag \
  --param enabled=true \
  --yes
```

Résultat fusionné dans `config/http.yaml`:

```yaml
etag:
  enabled: true
```

Quand `enabled: true`, `Arclith.fastapi()` ajoute `ETaggerMiddleware`. Le middleware concerne les
réponses `GET` JSON `2xx` qui contiennent `version` ou `data.version`: il ajoute `ETag: "v<version>"`
et retourne `304 Not Modified` sans body si `If-None-Match` correspond. Les mutations ne reçoivent
pas de header de cache en sortie; `If-Match` sur `PUT`/`PATCH` est seulement exposé via
`request.state.expected_version` pour que la route ou le service valide l'optimistic locking.

```bash
arclith-cli add-adapter \
  --capability http \
  --adapter cache-control \
  --param get_single_max_age=300 \
  --param get_list_max_age=60 \
  --yes
```

Résultat fusionné dans `config/http.yaml`:

```yaml
cache_control:
  get_single_max_age: 300
  get_list_max_age: 60
```

`CacheControlMiddleware` est ajouté par `Arclith.fastapi()` et ne nécessite pas de modification des
routers. Les `GET` vers une ressource unique détectée par un segment UUID-like reçoivent
`private, max-age=<get_single_max_age>`. Les collections reçoivent
`private, max-age=<get_list_max_age>`; si `get_list_max_age: 0`, elles reçoivent `no-store`.
Les mutations `POST`, `PUT`, `PATCH` et `DELETE` restent non cacheables avec
`no-cache, no-store, must-revalidate`. Si une route définit déjà `Cache-Control`, le middleware
préserve ce header. Les TTL négatifs sont refusés au chargement de config.

### `mcp`

Capacité inbound pour exposer les cas d'usage via MCP.

Adapter disponible:

- `fastmcp`: serveur FastMCP configuré par `Arclith.fastmcp()`, `run_mcp_sse()` et
  `run_mcp_http()`.

Configuration runtime:

```yaml
# config/adapters/inbound/fastmcp.yaml
host: 127.0.0.1
port: 8001
```

Cette capacité n'a pas de clé d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/inbound/fastmcp.yaml` est chargé directement dans `AppConfig.mcp`.

FastMCP expose les mêmes use cases que l'API, via tools/resources/prompts définis dans le projet
consommateur. Les tools MCP appellent les ports inbound ou use cases applicatifs; ils ne doivent pas
contourner l'application pour appeler un repository concret.

Transports supportés par Arclith:

- `run_mcp_sse(mcp)`: lance FastMCP avec `transport="sse"`, `host` et `port` depuis `AppConfig.mcp`;
- `run_mcp_http(mcp)`: lance FastMCP avec `transport="streamable-http"`, `host` et `port` depuis
  `AppConfig.mcp`.

`stdio` n'a pas de runner Arclith: utiliser SSE ou streamable HTTP pour garder un déploiement
compatible API/MCP/probes. L'instrumentation MCP reste transverse: enregistrer les tools sur
`mcp`, puis appeler `Arclith.instrument_mcp(mcp)` si les probes sont activées. Cette instrumentation
ne fait pas partie de la capability `mcp/fastmcp`.

### `probe`

Capacité inbound transverse pour configurer le serveur de probes Arclith. Elle ne dépend d'aucun
adapter métier: l'application enregistre ses readiness checks et Arclith expose les transports
actifs via `run_with_probes(..., transports=[...])`.

Adapter disponible:

- `server`: serveur HTTP léger exposant `/health`, `/ready`, `/info` et `/metrics`.

```bash
arclith-cli add-adapter \
  --capability probe \
  --adapter server \
  --param host=127.0.0.1 \
  --param port=9000 \
  --param enabled=true \
  --yes
```

Résultat:

```yaml
# config/adapters/inbound/probe.yaml
host: 127.0.0.1
port: 9000
enabled: true
```

Contrat HTTP réel:

- `GET /health`: `200`, `{"status": "ok"}`.
- `GET /ready`: `200`, `{"status": "ready"}` sans check ou si tous les checks retournent `True`;
  `503`, `{"status": "not_ready"}` si un check retourne `False` ou lève une exception.
- `GET /info`: service, version, Python, plateforme, uptime et `active_transports`.
- `GET /metrics`: `collected_at` et métriques par transport collecté, par exemple `api` et `mcp`.

Exemple de readiness DB côté application:

```python
async def db_ready() -> bool:
    await database.ping()
    return True

arclith.add_readiness_check(db_ready)
arclith.run_with_probes(_run_api, _run_mcp_http, transports=["api", "mcp_http"])
```

`enabled: false` conserve la configuration mais ne démarre pas de serveur en arrière-plan. Les
métriques MCP restent explicites: enregistrer les tools, puis appeler `arclith.instrument_mcp(mcp)`.

### `tenant`

Capacité inbound transverse pour résoudre un `TenantContext` depuis un claim JWT et Vault KV v2.
Elle s'utilise avec un repository tenant-level, par exemple `repository/mongodb` en
`multitenant: true`.

Adapter disponible:

- `vault`: configure `TenantSettings` pour `VaultTenantResolver`.

```bash
arclith-cli add-adapter \
  --capability tenant \
  --adapter vault \
  --param addr=http://vault:8200 \
  --param mount=kv \
  --param path_prefix=rekipe/tenants \
  --param tenant_claim=tenant_id \
  --param tenant_uri_ttl=300 \
  --yes
```

Résultat:

```yaml
# config/adapters/inbound/tenant.yaml
vault_addr: http://vault:8200
vault_mount: kv
vault_path_prefix: rekipe/tenants
tenant_claim: tenant_id

# config/adapters/inbound/cache.yaml
tenant_uri_ttl: 300
```

`tenant_uri_ttl` est fusionné dans `cache.yaml` sans écraser `backend`, `redis_url` ni `jwks_ttl`.
Les coordonnées sont génériques par adapter: un secret tenant peut fournir `uri`/`db_name` pour
MongoDB, ou `bucket_name`/`endpoint_url` pour un futur adapter S3. En mode single-tenant
(`multitenant: false`), `make_inject_tenant_uri` bypass le pipeline JWT/Vault sans erreur.

### `license`

Capacité inbound transverse pour valider un realm role Keycloak après décodage JWT. Elle ne génère
pas de router FastAPI ni de tool MCP: `Arclith.auth_dependency()` applique la même règle aux deux
transports quand `config.license` est présent.

Adapter disponible:

- `role`: configure `LicenseSettings.role` et utilise `RoleLicenseValidator`.

```bash
arclith-cli add-adapter \
  --capability license \
  --adapter role \
  --param role=rekipe:licensed \
  --yes
```

Résultat:

```yaml
# config/adapters/inbound/license.yaml
role: rekipe:licensed
```

L'absence de `config/adapters/inbound/license.yaml` désactive la vérification de licence sans
changer les routes. Les erreurs restent séparées: `401` pour une authentification manquante ou
invalide, `403` pour un token valide sans le rôle configuré.

### `llm`

Capacité outbound pour configurer le modèle utilisé par les interpréteurs d'intention et agents.

Adapters disponibles:

- `lmstudio`: LLM local exposé par LM Studio via endpoint OpenAI-compatible;
- `openai`: modèle OpenAI via protocole OpenAI-compatible;
- `anthropic`: modèle Anthropic.

Configuration runtime:

```yaml
# config/adapters/outbound/lm.yaml
provider: openai
model_name: "qwen/qwen3.5-9b"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
```

Cette capacité n'a pas de clé d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/outbound/lm.yaml` est chargé directement dans `AppConfig.adapters.lm`.

Pour LM Studio, `model_name` doit correspondre au modèle réellement chargé dans l'application
locale. L'`api_key` peut rester une valeur factice comme `lm-studio` si LM Studio n'authentifie pas
les requêtes. Les tests Arclith valident uniquement la construction du provider OpenAI-compatible;
ils n'appellent pas de modèle réel.

Choisir le `base_url` selon l'emplacement du processus qui exécute Arclith:

- service lancé sur la même machine que LM Studio: `http://127.0.0.1:1234/v1`;
- service lancé dans Docker et LM Studio sur l'hôte: `http://host.docker.internal:1234/v1`;
- service et LM Studio dans le même réseau Docker: utiliser le nom DNS du service LM Studio.

Pour OpenAI et Anthropic, la CLI génère `config/secrets.yaml` avec un resolver `env`, afin que
`adapters.lm.api_key` soit alimenté par `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY` sans écrire la clé
dans `lm.yaml`.

Pour OpenAI, `model_name` est un placeholder généré par défaut: passer explicitement le modèle
souhaité via `--param model_name=...`. La clé réelle ne doit pas être commitée: soit elle est passée
à la CLI pour être fusionnée dans `.env` local gitignoré, soit elle est fournie au runtime par
variable d'environnement, soit `config/secrets.yaml` est basculé vers un resolver Vault. Si le
resolver `env` est actif et que `OPENAI_API_KEY` manque au démarrage, `load_config_dir()` échoue avec
un message `Secrets non résolus` qui liste `adapters.lm.api_key`.

Choisir `llm/anthropic` pour utiliser les modèles Claude via le provider Anthropic. Choisir
`llm/openai` lorsque le modèle est exposé par le protocole OpenAI-compatible: OpenAI, LM Studio,
Ollama ou un endpoint custom via `base_url`. Anthropic ne génère pas de `base_url`; la clé réelle est
résolue de la même façon via `ANTHROPIC_API_KEY`, l'environnement runtime ou Vault.

### `observability`

Capacité outbound pour brancher l'observabilité et le banc de test agent.

Adapters disponibles:

- `langsmith`: tracing LangSmith et exécution locale dans LangGraph Studio;
- `opentelemetry`: export OTLP traces/metrics et instrumentation FastAPI.

Activation:

```yaml
observability:
  enabled:
    - langsmith
    - opentelemetry
```

La liste peut contenir un seul adapter ou les deux. Arclith ne garde pas de sélecteur unique
pour l'observabilité: LangSmith et OpenTelemetry peuvent être actifs en parallèle.

Arclith considère LangSmith Studio comme l'endroit standard pour tester un agent. Le serveur local
LangGraph doit lire `.env` via `langgraph.json`; `.env` contient `LANGSMITH_API_KEY`,
`LANGSMITH_TRACING`, `LANGSMITH_PROJECT` et `LANGSMITH_ENDPOINT`. La clé reste locale et ne doit pas
être commitée.

`config/adapters/outbound/langsmith.yaml` stocke seulement `api_key_env: LANGSMITH_API_KEY`: si la
clé n'est pas passée à la CLI, aucune valeur vide n'est ajoutée à `.env`. Définir explicitement
`LANGSMITH_API_KEY` dans `.env`, l'environnement runtime ou le secret manager avant de lancer
`langgraph dev`, sinon les runs LangSmith ne pourront pas être envoyés. `project` nomme le workspace
ou projet de test LangSmith, `endpoint` permet de viser l'API régionale, et `tracing` pilote
`LANGSMITH_TRACING`.

OpenTelemetry se configure avec:

```yaml
# config/adapters/outbound/opentelemetry.yaml
service_name: "my-service"
endpoint: "http://localhost:4318"
traces_endpoint: null
metrics_endpoint: null
protocol: "http/protobuf"
headers_env: OTEL_EXPORTER_OTLP_HEADERS
traces: true
metrics: false
instrument_fastapi: true
metrics_export_interval_millis: 60000
```

`opentelemetry.yaml` décrit l'export OTLP. L'activation reste uniquement dans
`config/adapters/adapters.yaml`, via `observability.enabled`.

Pour renseigner l'environnement sans le coder dans l'application, définir une ressource standard au
runtime:

```bash
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local
```

Quand `instrument_fastapi` et `traces` sont actifs, `Arclith.fastapi()` installe
l'instrumentation FastAPI après les middlewares Arclith. Les logs Arclith ajoutent `trace_id` et
`span_id` aux métadonnées quand un span courant existe. FastMCP et LangGraph ne reçoivent pas encore
de spans manuels par tool ou par nœud dans le framework: en local, LangSmith reste le banc de test
agent, et OpenTelemetry couvre le processus/runtime uniquement quand il est instrumenté par le SDK ou
par le serveur hôte.

Installer l'extra avant d'activer l'adapter:

```bash
uv add "arclith[opentelemetry]"
```

### `agent`

Capacité inbound pour exposer les cas d'usage métier via un runtime agent.

Adapter disponible:

- `langgraph`: entrypoint LangGraph Studio base sur la tuyauterie Arclith.

Configuration runtime:

L'adapter `langgraph` suit la convention produit des adapters inbound comme `fastapi` et `fastmcp`:
`config/adapters/inbound/langgraph.yaml` est chargé dans `AppConfig.langgraph`. Il n'ajoute pas de
clé générique `adapters.agent` dans `config/adapters/adapters.yaml`.

L'adapter génère:

- `langgraph.json`;
- `config/adapters/inbound/langgraph.yaml`;
- `src/<package>/adapters/inbound/langgraph/agent.py`.

Le fichier `agent.py` est le seul point à modifier pour un nouveau projet agent: l'état, les nœuds,
les transitions et les appels aux cas d'usage applicatifs. Arclith garde le câblage récurrent:
chargement de configuration, création du `StateGraph`, compilation, entrypoint Studio et lecture de
`.env`.

Le flux cible reste: humain ou canal conversationnel -> LangGraph Agent Server -> `agent.py` ->
ports applicatifs -> use cases. Un LLM se branche derrière `LLMPort` via `config/adapters/outbound/lm.yaml`;
l'observabilité se branche via `observability.enabled` (`langsmith`, `opentelemetry`, ou les deux).
Les nodes LangGraph ne doivent pas appeler les repositories directement: ils traduisent l'intention,
préparent des commandes ou DTO, puis appellent les ports et use cases du projet.

## Ajouter un adapter

Le chemin standard est:

```bash
arclith-cli add-adapter --capability repository --adapter mongodb --entity Ingredient --yes
```

Les paramètres d'adapter peuvent être fournis de manière générique:

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mariadb \
  --entity Ingredient \
  --param host=127.0.0.1 \
  --param port=3306 \
  --param database=pantry_agent \
  --param user=app \
  --yes
```

Le mode interactif reste disponible:

```bash
arclith-cli add-adapter
```

Pour brancher le banc de test agent LangSmith:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name=qwen/qwen3.5-9b \
  --yes

arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph

arclith-cli add-adapter \
  --capability api \
  --adapter fastapi \
  --param port=8080 \
  --yes

arclith-cli add-adapter \
  --capability mcp \
  --adapter fastmcp \
  --param port=8081 \
  --yes

arclith-cli add-adapter \
  --capability cache \
  --adapter memory \
  --yes

arclith-cli add-adapter \
  --capability cache \
  --adapter redis \
  --param redis_url=redis://redis:6379 \
  --yes

arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith
```

En mode interactif, la CLI demande aussi `LANGSMITH_API_KEY` et l'écrit dans `.env`. Le mode direct
reste possible pour les scripts:

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --param project=my-agent-dev \
  --param endpoint=https://api.smith.langchain.com \
  --param api_key="$LANGSMITH_API_KEY" \
  --yes
```

Pour OpenTelemetry:

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter opentelemetry \
  --param service_name=my-service \
  --param endpoint=http://localhost:4318 \
  --param metrics=true \
  --yes
```

Ces deux commandes ajoutent chacune leur adapter dans `observability.enabled`; elles ne se
remplacent pas.

Pour OpenAI:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter openai \
  --param model_name="<model-id-openai>" \
  --param api_key="$OPENAI_API_KEY" \
  --yes
```

Pour Anthropic:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter anthropic \
  --param model_name="<model-id-anthropic>" \
  --param api_key="$ANTHROPIC_API_KEY" \
  --yes
```

## Règle d'évolution

Chaque nouvelle capacité technique doit d'abord être ajoutée au catalogue, puis consommée par la CLI.
Cela garde les futures briques, par exemple MariaDB, bus, tracing ou observability, déclaratives et
testables.

Une capacité ne doit pas introduire de dépendance du core vers un adapter. Elle doit uniquement
générer ou câbler les éléments externes nécessaires.

Les secrets ne doivent pas être générés dans les fichiers d'adapter. Pour MariaDB, mapper
`adapters.mariadb.password` ou `adapters.mariadb.url` via `config/secrets.yaml`, un resolver `env`
ou Vault. Pour les LLMs distants, mapper `adapters.lm.api_key` vers `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY` ou la variable cible.
