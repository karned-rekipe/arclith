# arclith-cli

`arclith-cli` construit un projet Python hexagonal par étapes. `init` pose uniquement le socle
installable ; chaque adapter, transport et dépendance optionnelle est ensuite ajouté explicitement.
`new` reste disponible comme raccourci compatible pour `init` suivi de `add-entity`, sans adapter
implicite.

## Installation

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
```

## Commandes

Exécuter `arclith-cli` sans argument affiche cette liste de commandes et termine sans erreur.

### `init` — Initialiser un projet minimal

Crée un projet Arclith vide de métier, avec le layout canonique `src/<package>/...`, une
configuration minimale et un `main.py` prêt à recevoir les adapters. Les fichiers du runtime
Docker (`Dockerfile`, `.dockerignore`, `arclith-run`) ne sont ajoutés que par
`add-adapter --capability runtime --adapter docker-image`.

```bash
# Mode interactif
arclith-cli init

# Mode direct
arclith-cli init todo-list-service
arclith-cli init todo-list-service --dir ~/projects
```

Cette commande ne crée aucune entité, aucun CRUD et aucun endpoint métier. Elle sert quand on veut
construire le projet étape par étape avec `add-entity`, `add-blueprint`, `add-usecase`, puis
`add-adapter`.
Elle ne crée pas non plus FastAPI ou FastMCP et n'installe aucun de leurs extras.

#### Pourquoi `src/<package>/...` ?

`src/` est la racine des imports du projet installé ; `<package>` est le namespace propre au
service. Les couches restent donc importées comme `todo_service.domain` ou
`todo_service.application`, au lieu de créer des packages Python globaux et génériques nommés
`domain`, `application` et `adapters`. Cette structure évite les collisions, empêche les tests
d'importer accidentellement le dépôt courant à la place du package installé et suit le `src layout`
standard de l'écosystème Python.

#### Parcours complet vers une API

```bash
arclith-cli init todo-api
cd todo-api
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo

# Choisir explicitement la persistance et le transport utilisés.
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability api --adapter fastapi --param port=8765 --yes

arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
uv sync
MODE=api uv run python main.py
```

Le parcours fonctionne avec les seuls champs techniques de `Entity`. Le composition root typé
est régénéré automatiquement pour un use case sans dépendance ou avec une dépendance
`Repository[Entity]`. Une composition plus riche reste explicite. Voir le
[guide des bindings](https://karned-rekipe.github.io/arclith/deep-dives/use-case-bindings/).

Pour initialiser plutôt les cinq opérations CRUD, utiliser
`add-entity Todo --profile crud`. Ce blueprint crée le cœur applicatif et sa
composition, mais aucun endpoint. Après installation explicite de FastAPI, la
projection REST complète tient en une commande distincte :

```bash
arclith-cli add-entity Todo --profile crud
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

Les projections FastMCP, RabbitMQ ou LangGraph restent des décisions distinctes
avec une sémantique propre au transport.

---

### `new` — Raccourci minimal compatible

`new` exécute le même scaffold canonique que `init`, puis ajoute l'entité
demandée avec le profil `minimal` par défaut. Le profil `crud` reste explicite.
Aucun adapter, transport ou runtime Docker n'est créé implicitement.

```bash
# Mode interactif — l'outil pose les questions
arclith-cli new

# Mode direct
arclith-cli new Recipe my-recipe-service
arclith-cli new RecipeStep meal-planner --port 8400
arclith-cli new MealPlan meal-plan-service --dir ~/projects --port 8500
arclith-cli new Todo todo-service --profile crud
```

| Option | Défaut | Description |
|--------|--------|-------------|
| `--port` / `-p` | `8000` | Port à proposer lors du futur ajout explicite de FastAPI |
| `--dir` / `-d` | `.` | Répertoire parent |
| `--profile` | `minimal` | Profil applicatif initial (`minimal` ou `crud`) |

Le projet généré utilise un layout `src/<package>/...` pour le code applicatif et un dossier
`config/` structuré par adapter (voir section [Configuration](#configuration)). Utiliser ensuite
`add-usecase`, `add-adapter` puis `expose-usecase`, ou le couple
`add-entity --profile crud` puis `expose-feature`; un Dockerfile n'apparaît que
via l'adapter `runtime/docker-image`.

---

### `add-entity` — Ajouter une entité métier

Crée un squelette minimal et guidé dans `src/<package>/domain/models/`. Le fichier
signale où déclarer les champs et invariants, rappelle les champs déjà fournis par
`Entity` et renvoie vers les guides Arclith et Pydantic. L'exemple `Field(...)`
reste commenté, donc aucun import inutilisé n'est ajouté.

```bash
cd my-recipe-service
arclith-cli add-entity ShoppingItem
arclith-cli add-entity Todo --profile crud
```

Fichier généré :

```text
src/<package>/domain/models/shopping_item.py
```

Sans `--profile`, le mode direct conserve le profil `minimal` et ne génère aucun
CRUD, port repository, adapter ou endpoint. En interactif, la CLI demande de
choisir `minimal` ou `crud`. Le profil `crud` initialise les ports inbound, use
cases, erreurs, composition et tests du cycle `create/get/list/update/delete`,
sans créer d'adapter.

---

### `blueprints` et `add-blueprint` — Initialiser un comportement applicatif

Le catalogue des blueprints est distinct du catalogue des capabilities et des
adapters :

```bash
arclith-cli blueprints
arclith-cli blueprints --json
arclith-cli add-blueprint crud --entity ShoppingItem --dry-run
arclith-cli add-blueprint crud --entity ShoppingItem
```

La première application écrit `.arclith/features/shopping_item.yaml`. Un replay
préserve les fichiers applicatifs déjà personnalisés et complète uniquement les
fichiers manquants. Le CRUD est une possibilité parmi les futurs blueprints ;
il n'est jamais inféré depuis un adapter. Voir le
[contrat détaillé](https://karned-rekipe.github.io/arclith/blueprints/).

---

### `expose-feature` — Projeter Un Blueprint Applicatif

Consomme le manifeste `.arclith/features/<feature>.yaml` créé par un blueprint
et projette ses opérations vers un adapter déjà installé. La première version
supporte le blueprint `crud` vers FastAPI :

```bash
arclith-cli add-entity Todo --profile crud
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature todo --via fastapi --path /v1/todos --dry-run
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

Sans `--path`, la collection utilise `/v1/<feature>` sans pluralisation
automatique. La commande planifie ensemble les routes `POST`, `GET` collection,
`GET` item, `PATCH` et `DELETE`, leurs DTO et leur composition partagée, puis
n'écrit qu'après validation complète du lot. Les
erreurs applicatives `NotFound` et `VersionConflict` deviennent `404` et `409`.
Elle ne crée ni adapter ni repository. Les fichiers développeur sont préservés
à la relance et la recette n'enregistre que la première mutation effective.

Utiliser `expose-usecase` pour une opération isolée ou un comportement qui ne
provient pas d'un blueprint.

---

### `add-usecase` — Ajouter un cas d'usage

Crée un port inbound guidé dans `src/<package>/domain/ports/inbound/`, puis le
cas d'usage dans `src/<package>/application/use_cases/`. Sans option de liaison,
la commande interactive propose les entités détectées par analyse AST, la
création d'une nouvelle entité ou un cas d'usage transverse.

```bash
cd my-recipe-service

# Mode interactif : choisir une entité détectée, en créer une ou rester transverse
arclith-cli add-usecase PlanShoppingList

# Modes directs, complets pour les agents et la CI
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-usecase CreateRecipe --new-entity Recipe
arclith-cli add-usecase RunMaintenance --no-entity
```

| Option | Effet |
|---|---|
| `--entity Todo` | lie le use case à une entité détectée et échoue si elle est absente |
| `--new-entity Todo` | crée l'entité si nécessaire, puis génère le use case lié |
| `--no-entity` | génère un `Command`, un `Result` et un use case transverse sans repository |

Ces options sont mutuellement exclusives. `--new-entity` réutilise une entité
valide déjà présente, mais refuse un fichier homonyme qui ne déclare pas la
classe `Entity` attendue.

Fichier généré :

```text
src/<package>/domain/ports/inbound/plan_shopping_list.py
src/<package>/application/use_cases/plan_shopping_list.py
```

Le nom peut être fourni en PascalCase, snake_case ou kebab-case. Le suffixe
`UseCase` est normalisé : `PlanShoppingListUseCase` et
`plan-shopping-list-use-case` génèrent tous les deux
`PlanShoppingListUseCase`.

Pour une entité principale, le squelette injecte explicitement
`Repository[Entity]` et type `execute` avec un `Command` Pydantic et l'entité en
retour. Le mode transverse génère plutôt un `Command` et un `Result` Pydantic,
sans repository implicite. Aucun mode ne câble FastAPI, FastMCP ou LangGraph.
Les exemples complets et les règles de séparation sont dans le
[deep dive du scaffold CLI](https://karned-rekipe.github.io/arclith/deep-dives/cli-scaffold/).

---

### `add-intent-interpreter` — Ajouter un interpréteur d'intention

Crée uniquement le fichier minimal d'un interpréteur d'intention dans
`src/<package>/application/intent_interpreters/`.

```bash
cd my-recipe-service
arclith-cli add-intent-interpreter IngredientIntent
arclith-cli add-intent-interpreter command-router
```

Fichier généré :

```text
src/<package>/application/intent_interpreters/ingredient_intent.py
```

L'interpréteur d'intention est le composant applicatif qui transforme une demande naturelle en
commande ou DTO structuré. Il ne remplace pas LangGraph : LangGraph orchestre les nœuds, tandis que
l'interpréteur porte la traduction d'intention. Le fichier généré reste volontairement vide de
logique métier.

---

### `add-adapter` — Ajouter un adapter

Wizard interactif à lancer **depuis la racine du projet cible**. Sans option, il affiche toutes les
capabilities et leurs adapters, notamment `api/fastapi` et `mcp/fastmcp`, puis demande le choix.
Il scaffold uniquement le code, la configuration et l'extra de dépendance du choix effectué.

```bash
cd my-recipe-service
arclith-cli add-adapter
```

Mode direct, utile pour CI, scripts de migration ou commandes reproductibles :

```bash
arclith-cli add-adapter --adapter mongodb --db-name my_recipe_service --param collection_name=recipes --yes
arclith-cli add-adapter --adapter duckdb --path data/ --no-activate --yes
arclith-cli add-adapter --adapter mariadb --param database=my_recipe_service --param user=app --yes
arclith-cli add-adapter --capability api --adapter fastapi --param port=8080 --yes
arclith-cli add-adapter --capability mcp --adapter fastmcp --param port=8081 --yes
arclith-cli add-adapter --capability llm --adapter lmstudio --param model_name=qwen/qwen3.5-9b --yes
arclith-cli add-adapter --capability agent --adapter langgraph --param graph_name=recipe_agent --param stream_mode=updates,custom --yes
arclith-cli add-adapter --capability observability --adapter langsmith
arclith-cli add-adapter --capability observability --adapter opentelemetry --param service_name=my_recipe_service --yes
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
arclith-cli add-adapter --capability cache --adapter memory --yes
arclith-cli add-adapter --capability cache --adapter redis --param redis_url=redis://redis:6379 --yes
arclith-cli add-adapter --capability repository --adapter memory --yes
```

**Étapes du wizard :**

1. **Capability** — toutes les capabilities du catalogue sont proposées avec leurs adapters
2. **Type d'adapter** — selon la capability : `memory` · `mongodb` · `duckdb` · `mariadb` · `fastapi` · `fastmcp` · `rabbitmq` · `docker-image` · `lmstudio` · `openai` · `anthropic` · `langgraph` · `langsmith` · `opentelemetry`
3. **Entité(s) cible(s)** — uniquement pour une extension explicitement déclarée entity-scoped ; les repositories génériques et les transports ne demandent pas d'entité
4. **Paramètres** — questions spécifiques à l'adapter :
   - `mongodb` → `db_name`, `collection_name`, `multitenant`
   - `duckdb` → `path`
   - `mariadb` → `host`, `port`, `database`, `user`, `driver`, `table_prefix`
     (`url` et `password` sont mappés via `config/secrets.yaml`)
   - `cache/memory` → `jwks_ttl`, `tenant_uri_ttl`
   - `cache/redis` → `redis_url`, `jwks_ttl`, `tenant_uri_ttl`
   - `fastapi` → `host`, `port`, `reload`
   - `fastmcp` → `host`, `port`
   - `lmstudio` → `model_name`, `base_url`, `api_key`
   - `openai` → `model_name`, `base_url`, `OPENAI_API_KEY`
   - `anthropic` → `model_name`, `ANTHROPIC_API_KEY`
   - `langgraph` → `graph_name`, `stream_mode`
   - `langsmith` → `tracing`, `project`, `endpoint`, `LANGSMITH_API_KEY`
   - `opentelemetry` → `service_name`, `endpoint`, `traces_endpoint`, `metrics_endpoint`, `protocol`, `traces`, `metrics`, `instrument_fastapi`
   - `command-bus/rabbitmq` → `url`, `exchange`, `exchange_type`, `queue`, `routing_key`, `prefetch`, `consumer_name`, `concurrency`, `publisher_confirms`, `durable`, `retry_enabled`, `retry_requeue`, `dead_letter_exchange`, `dead_letter_routing_key`
   - `runtime/docker-image` → `uv_version`, `api_port`, `mcp_port`, `probe_port`, `agent_port`
   - `repository/memory` → aucun paramètre
5. **Activation** — met à jour `config/adapters/adapters.yaml` pour les capacités activables (`repository: <adapter>` ou `observability.enabled: [<adapter>, ...]`) ; `api/fastapi`, `mcp/fastmcp`, `cache/*`, `llm/*`, `agent/langgraph`, `command-bus/rabbitmq` et `runtime/docker-image` sont exposés par leurs fichiers dédiés
6. **Récapitulatif** — liste des fichiers créés ou remplacés avant confirmation

| Option | Défaut | Description |
|--------|--------|-------------|
| `--capability` | interactif | Capacité cible du catalogue standardisé (`repository`, `cache`, `api`, `mcp`, `http`, `command-bus`, `runtime`, `llm`, `agent`, `observability`) |
| `--adapter` / `-a` | interactif | Adapter du catalogue : `memory`, `mongodb`, `duckdb`, `mariadb`, `fastapi`, `fastmcp`, `idempotency`, `etag`, `cache-control`, `rabbitmq`, `docker-image`, `lmstudio`, `openai`, `anthropic`, `langgraph`, `langsmith`, `opentelemetry` |
| `--activate/--no-activate` | `--activate` | Met à jour `config/adapters/adapters.yaml` quand la capacité expose une clé d'activation |
| `--db-name` | nom du projet | Nom de base pour MongoDB |
| `--multitenant/--single-tenant` | `--single-tenant` | Mode MongoDB multitenant |
| `--path` | `data/` | Chemin DuckDB |
| `--param` | - | Paramètre adapter `key=value`, répétable pour les adapters du catalogue |
| `--yes` / `-y` | `false` | Skip la confirmation et utilise les valeurs fournies ou par défaut |

**Contrat d'un repository intégré :**

```
config/adapters/outbound/<adapter>.yaml          # config scopée si l'adapter en a besoin
src/<package>/adapters/outbound/<adapter>/__init__.py
src/<package>/adapters/outbound/<adapter>/README.md
src/<package>/adapters/outbound/<adapter>/repositories/        # extensions custom uniquement
src/<package>/infrastructure/use_cases_generated.py            # composition des use cases exposés
```

Les implémentations CRUD sont fournies par Arclith et sélectionnées par
`arclith.repository(Entity)`. Aucun repository par entité, container ou adapter
`memory` de secours n'est généré. Le README de chaque rôle définit les seuls
emplacements autorisés pour une extension provider spécifique.

**Runtime Docker :**

```bash
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
uv lock
docker build -t my-recipe-service:local .
docker run --rm -p 8000:8000 -p 9000:9000 my-recipe-service:local api
```

L'adapter `runtime/docker-image` génère `Dockerfile`, `.dockerignore` et `arclith-run`. Une seule
image peut démarrer `api`, `mcp_http`, `mcp_sse`, `bus`, `agent` ou `all` par argument ou via
`ARCLITH_RUNTIME_MODE`. Les secrets restent hors build; `.env`, `secrets.yaml` et les clés privées
sont exclus du contexte Docker.

**LangGraph / LangSmith :**

```bash
uv add "arclith[langgraph]"
arclith-cli add-adapter --capability llm --adapter lmstudio --param model_name=qwen/qwen3.5-9b --yes
arclith-cli add-adapter --capability agent --adapter langgraph
arclith-cli add-adapter --capability observability --adapter langsmith
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

L'adapter `llm/lmstudio` génère `config/adapters/outbound/lm.yaml`, chargé dans
`AppConfig.adapters.lm`. Adapter `model_name` au modèle chargé dans LM Studio et utiliser
`host.docker.internal` comme `base_url` si le projet tourne dans Docker alors que LM Studio tourne
sur l'hôte. Les adapters `llm/openai` et `llm/anthropic` génèrent aussi un mapping
`config/secrets.yaml` vers `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`; la clé réelle reste dans `.env`
local gitignoré, l'environnement runtime ou Vault.
Utiliser `llm/anthropic` pour Claude via le provider Anthropic; utiliser `llm/openai` pour OpenAI,
LM Studio ou tout endpoint OpenAI-compatible avec `base_url`.

L'adapter `repository/mongodb` génère `config/adapters/outbound/mongodb.yaml` avec `uri: null`, puis
mappe `adapters.mongodb.uri` vers `MONGODB_URI` dans `config/secrets.yaml`. L'URI réelle reste dans
l'environnement, un fichier local de secrets ou Vault selon le resolver choisi.
Il ne génère pas de repository `memory` applicatif. L'implémentation mémoire du framework peut être
utilisée directement dans des tests ; une spécialisation mémoire du projet n'est créée que par un
choix explicite de `repository/memory`.

L'adapter `agent/langgraph` génère `langgraph.json`, `config/adapters/inbound/langgraph.yaml` et
`src/<package>/adapters/inbound/langgraph/agent.py`. Le projet ne modifie ensuite que ce fichier pour
son agent. Comme `fastapi` et `fastmcp`, LangGraph est configuré par son nom produit dans
`AppConfig.langgraph`, sans `adapters.agent`. `stream_mode` vaut `updates` par défaut et accepte une
liste CSV comme `updates,custom` pour exposer les sorties de nodes et les événements
`get_stream_writer()`. L'adapter `observability/langsmith` génère
`config/adapters/outbound/langsmith.yaml`, l'ajoute à `observability.enabled`, met
à jour `.env` et ajoute `.env` au `.gitignore` si besoin. LangSmith Studio devient l'endroit standard
pour tester les agents. Une `LANGSMITH_API_KEY` déjà présente est conservée si aucune nouvelle valeur
n'est fournie.

**OpenTelemetry :**

```bash
uv add "arclith[opentelemetry]"
arclith-cli add-adapter --capability observability --adapter opentelemetry --param service_name=my-recipe-service --yes
```

L'adapter `observability/opentelemetry` génère `config/adapters/outbound/opentelemetry.yaml`, met à
jour `.env`, l'ajoute à `observability.enabled` et branche l'instrumentation FastAPI quand
`Arclith.fastapi()` construit l'application. Il peut être activé en même temps que LangSmith.
Le fichier `opentelemetry.yaml` ne porte pas de flag `enabled`: l'activation se fait uniquement dans
`observability.enabled`.
L'endpoint global est utilisé par défaut; `traces_endpoint` et `metrics_endpoint` peuvent cibler des
routes OTLP distinctes. Pour taguer l'environnement, définir
`OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local` dans l'environnement runtime.

Parcours complet avec entité, API, LangGraph, LangSmith et LM Studio:
[`docs/agent-quickstart.md`](../docs/agent-quickstart.md).

---

### `capabilities` — Lister le catalogue standardisé

Affiche les capacités et adapters connus par la CLI.

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

Le catalogue est la source de vérité pour les adapters supportés, leurs paramètres, leur chemin de configuration et la clé d'activation.

---

### `export-config` — Générer `config.yaml` pour K8s

Fusionne le dossier `config/` en un fichier YAML unique, à lancer **depuis la racine du projet**.

```bash
arclith-cli export-config                        # → ./config.yaml
arclith-cli export-config --output dist/app.yaml # chemin personnalisé
```

Le fichier généré peut être monté directement comme **ConfigMap** Kubernetes.
Arclith le lit au même titre que le dossier `config/` :

```python
# dev
arclith = Arclith("config/")

# K8s (ConfigMap monté sur /app/config.yaml)
arclith = Arclith("config.yaml")
```

> ⚠️ `config.yaml` est un **artefact généré** — l'ajouter à `.gitignore`.
> La source de vérité reste `config/`.

---

### `history` et `replay` — Relire et rejouer les décisions CLI

`init`, `new`, `add-entity`, `add-blueprint`, `add-usecase`,
`add-intent-interpreter`, `add-adapter`, `expose-usecase` et `expose-feature`
ajoutent une étape à
`arclith.recipe.yaml` uniquement après leur
succès complet. La recette est un historique fonctionnel rejouable ; Git reste
l'historique du code et `export-config` reste la configuration consolidée de
déploiement.

```bash
arclith-cli history
arclith-cli replay arclith.recipe.yaml --dir ../rebuilt-service --dry-run
arclith-cli replay arclith.recipe.yaml --dir ../rebuilt-service
```

Sélectionner une plage avec `--from-step 0003` et `--to-step 0008`. Utiliser
`--strict` pour refuser une commande non supportée.

Les paramètres secrets sont remplacés par `<redacted>` et référencent une
variable d'environnement. Le dry-run liste les variables requises sans lire
leur valeur ; le replay réel exige qu'elles soient définies. Les chemins de
fichiers générés restent relatifs à la racine du projet et les étapes rejouées
ne sont pas enregistrées une seconde fois.

Voir la documentation complète :
[Recettes Arclith CLI](https://karned-rekipe.github.io/arclith/cli-recipe/).

---

### `update` — Mettre à jour le CLI

```bash
arclith-cli update
```

### `version` — Afficher la version

```bash
arclith-cli version
```

---

## Configuration

Les projets arclith utilisent un dossier `config/` à la place d'un `config.yaml` monolithique. Chaque fichier est **scopé** : son chemin détermine la section `AppConfig` dans laquelle son contenu est injecté.

```
config/
  app.yaml                        # app: { name, version, description }
  soft_delete.yaml                # soft_delete: { retention_days }
  secrets.yaml                    # secrets: { resolver, mappings, vault, yaml }
  adapters/
    adapters.yaml                 # adapters: { logger, repository, observability.enabled }
    outbound/
      mongodb.yaml                # adapters.mongodb: { db_name, multitenant }
      duckdb.yaml                 # adapters.duckdb: { path, multitenant }
      mariadb.yaml                # adapters.mariadb: { host, port, database, user, ... }
      lm.yaml                     # adapters.lm: { provider, model_name, api_key, base_url }
      langsmith.yaml              # adapters.langsmith: { tracing, project, endpoint, ... }
      opentelemetry.yaml          # adapters.opentelemetry: { endpoint, protocol, traces, metrics, ... }
    inbound/
      fastapi.yaml                # api: { host, port, reload }
      fastmcp.yaml                # mcp: { host, port }
      probe.yaml                  # probe: { host, port, enabled }
      keycloak.yaml               # keycloak: { url, realm }
      tenant.yaml                 # tenant: { vault_addr, … }
      license.yaml                # license: { role }
      cache.yaml                  # cache: { backend, redis_url, … }
```

`cache/memory` génère `config/adapters/inbound/cache.yaml` avec `backend: memory` et les TTL JWKS /
tenant. Ce cache est strictement local au processus Python: il suffit pour le développement, les
tests et un worker unique. Passer à Redis dès qu'il faut partager le cache entre plusieurs workers,
réplicas, ou processus séparés API/MCP/agent.

`cache/redis` génère le même fichier avec `backend: redis`, mappe `cache.redis_url` vers
`REDIS_URL` dans `config/secrets.yaml` et écrit la valeur fournie dans `.env` local gitignoré.
Installer l'extra avant de lancer le service:

```bash
uv add "arclith[cache]"
```

Pour changer l'adapter actif sans passer par le wizard :

```yaml
# config/adapters/adapters.yaml
repository: duckdb   # memory | mongodb | duckdb | mariadb
observability:
  enabled:
    - langsmith
    - opentelemetry
```

Pour MariaDB, ne committez pas le mot de passe ni l'URL complète si elle contient des identifiants.
La CLI mappe `adapters.mariadb.password` vers `MARIADB_PASSWORD` et `adapters.mariadb.url` vers
`MARIADB_URL` dans `config/secrets.yaml`; remplacer le resolver `env` par Vault selon l'environnement.
