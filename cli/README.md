# arclith-cli

`arclith-cli` génère instantanément un projet Python en architecture hexagonale prêt à démarrer, en téléchargeant le template officiel `_sample` depuis GitHub et en remplaçant l'entité de démo `Ingredient` par le nom de votre choix. Tout type de projet peut être scaffoldé — service REST, agent IA, API MCP — avec les ports, le nom de projet et le backend de persistance configurés d'emblée.

## Installation

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
```

## Commandes

### `init` — Initialiser un projet minimal

Crée un projet Arclith vide de métier, avec le layout canonique `src/<package>/...`, une
configuration minimale et un `main.py` prêt à recevoir les adapters.

```bash
# Mode interactif
arclith-cli init

# Mode direct
arclith-cli init todo-list-service
arclith-cli init todo-list-service --dir ~/projects
```

Cette commande ne crée aucune entité, aucun CRUD et aucun endpoint métier. Elle sert quand on veut
construire le projet étape par étape avec `add-entity`, `add-usecase`, puis `add-adapter`.

---

### `new` — Créer un projet

Scaffold un nouveau projet arclith depuis le template officiel `_sample`.

```bash
# Mode interactif — l'outil pose les questions
arclith-cli new

# Mode direct
arclith-cli new Recipe my-recipe-service
arclith-cli new RecipeStep meal-planner --port 8400
arclith-cli new MealPlan meal-plan-service --dir ~/projects --port 8500
```

| Option | Défaut | Description |
|--------|--------|-------------|
| `--port` / `-p` | `8000` | Port REST (MCP = port+1) |
| `--dir` / `-d` | `.` | Répertoire parent |
| `--ref` | `main` | Branche/tag du template |

Le projet généré utilise un layout `src/<package>/...` pour le code applicatif et un dossier `config/` structuré par adapter (voir section [Configuration](#configuration)).

---

### `add-entity` — Ajouter une entité métier

Crée uniquement le fichier minimal d'une entité dans `src/<package>/domain/models/`.

```bash
cd my-recipe-service
arclith-cli add-entity ShoppingItem
```

Fichier généré :

```text
src/<package>/domain/models/shopping_item.py
```

La commande ne génère aucun CRUD, aucun port repository, aucun adapter et aucun endpoint. Elle pose seulement le point d'ancrage du modèle métier ; le développeur complète ensuite les champs et invariants de l'entité.

---

### `add-usecase` — Ajouter un cas d'usage

Crée le port inbound minimal dans `src/<package>/domain/ports/inbound/`, puis le fichier minimal du
cas d'usage dans `src/<package>/application/use_cases/`.

```bash
cd my-recipe-service
arclith-cli add-usecase PlanShoppingList
arclith-cli add-usecase find-by-name
```

Fichier généré :

```text
src/<package>/domain/ports/inbound/plan_shopping_list.py
src/<package>/application/use_cases/plan_shopping_list.py
```

Le nom peut être fourni en PascalCase, snake_case ou kebab-case. Le suffixe `UseCase` est normalisé : `PlanShoppingListUseCase` et `plan-shopping-list-use-case` génèrent tous les deux `PlanShoppingListUseCase`.

Comme `add-entity`, cette commande ne câble pas FastAPI, FastMCP, LangGraph, un repository ou un service. Les adapters se branchent ensuite explicitement avec `add-adapter` et devraient dépendre du port inbound généré.

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

Wizard interactif à lancer **depuis la racine du projet cible**. Scaffold le code Python et/ou les fichiers de configuration pour un nouvel adapter. Par défaut, la capacité cible est `repository`.

```bash
cd my-recipe-service
arclith-cli add-adapter
```

Mode direct, utile pour CI, scripts de migration ou commandes reproductibles :

```bash
arclith-cli add-adapter --adapter mongodb --entity Recipe --db-name my_recipe_service --param collection_name=recipes --yes
arclith-cli add-adapter --adapter duckdb --all-entities --path data/ --no-activate --yes
arclith-cli add-adapter --adapter mariadb --entity Recipe --param database=my_recipe_service --param user=app --yes
arclith-cli add-adapter --capability api --adapter fastapi --param port=8080 --yes
arclith-cli add-adapter --capability mcp --adapter fastmcp --param port=8081 --yes
arclith-cli add-adapter --capability llm --adapter lmstudio --param model_name=qwen/qwen3.5-9b --yes
arclith-cli add-adapter --capability agent --adapter langgraph --param graph_name=recipe_agent --yes
arclith-cli add-adapter --capability observability --adapter langsmith
arclith-cli add-adapter --capability observability --adapter opentelemetry --param service_name=my_recipe_service --yes
arclith-cli add-adapter --capability repository --adapter memory --entity Recipe --yes
```

**Étapes du wizard :**

1. **Type d'adapter** — selon la capacité : `memory` · `mongodb` · `duckdb` · `mariadb` · `fastapi` · `fastmcp` · `lmstudio` · `openai` · `anthropic` · `langgraph` · `langsmith` · `opentelemetry`
2. **Entité(s) cible(s)** — détectées automatiquement pour les adapters entity-scoped ; ignorées pour les transports globaux, `llm/*`, `agent/langgraph` et les adapters d'observability
3. **Paramètres** — questions spécifiques à l'adapter :
   - `mongodb` → `db_name`, `collection_name`, `multitenant`
   - `duckdb` → `path`
   - `mariadb` → `host`, `port`, `database`, `user`, `driver`, `table_prefix`
     (`url` et `password` sont mappés via `config/secrets.yaml`)
   - `fastapi` → `host`, `port`, `reload`
   - `fastmcp` → `host`, `port`
   - `lmstudio` → `model_name`, `base_url`, `api_key`
   - `openai` → `model_name`, `base_url`, `OPENAI_API_KEY`
   - `anthropic` → `model_name`, `ANTHROPIC_API_KEY`
   - `langgraph` → `graph_name`
   - `langsmith` → `tracing`, `project`, `endpoint`, `LANGSMITH_API_KEY`
   - `opentelemetry` → `service_name`, `endpoint`, `traces_endpoint`, `metrics_endpoint`, `protocol`, `traces`, `metrics`, `instrument_fastapi`
   - `memory` → aucun paramètre
4. **Activation** — met à jour `config/adapters/adapters.yaml` pour les capacités activables (`repository: <adapter>` ou `observability.enabled: [<adapter>, ...]`) ; `api/fastapi`, `mcp/fastmcp`, `llm/*` et `agent/langgraph` sont exposés par leurs fichiers de configuration scopés
5. **Récapitulatif** — liste des fichiers créés ou remplacés avant confirmation

| Option | Défaut | Description |
|--------|--------|-------------|
| `--capability` | `repository` | Capacité cible du catalogue standardisé (`repository`, `api`, `mcp`, `llm`, `agent`, `observability`) |
| `--adapter` / `-a` | interactif | Adapter du catalogue : `memory`, `mongodb`, `duckdb`, `mariadb`, `fastapi`, `fastmcp`, `lmstudio`, `openai`, `anthropic`, `langgraph`, `langsmith`, `opentelemetry` |
| `--entity` / `-e` | auto si une seule entité | Entité cible, liste séparée par virgule acceptée |
| `--all-entities` | `false` | Génère l'adapter pour toutes les entités détectées |
| `--activate/--no-activate` | `--activate` | Met à jour `config/adapters/adapters.yaml` quand la capacité expose une clé d'activation |
| `--db-name` | nom du projet | Nom de base pour MongoDB |
| `--multitenant/--single-tenant` | `--single-tenant` | Mode MongoDB multitenant |
| `--path` | `data/` | Chemin DuckDB |
| `--param` | - | Paramètre adapter `key=value`, répétable pour les adapters du catalogue |
| `--yes` / `-y` | `false` | Skip la confirmation et utilise les valeurs fournies ou par défaut |

**Fichiers générés par entité :**

```
config/adapters/outbound/<adapter>.yaml          # config scopée si l'adapter en a besoin
src/<package>/adapters/outbound/<adapter>/__init__.py
src/<package>/adapters/outbound/<adapter>/repository.py        # re-export
src/<package>/adapters/outbound/<adapter>/repositories/<entity>_repository.py  # sous-classe à compléter
src/<package>/infrastructure/containers/<entity>_container.py  # RepositoryRegistry régénéré
```

> ⚠️ `src/<package>/infrastructure/containers/<entity>_container.py` est **régénéré intégralement** si le fichier existe déjà — un avertissement est affiché dans le récapitulatif.

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

L'adapter `repository/mongodb` génère `config/adapters/outbound/mongodb.yaml` avec `uri: null`, puis
mappe `adapters.mongodb.uri` vers `MONGODB_URI` dans `config/secrets.yaml`. L'URI réelle reste dans
l'environnement, un fichier local de secrets ou Vault selon le resolver choisi.

L'adapter `agent/langgraph` génère `langgraph.json`, `config/adapters/inbound/langgraph.yaml` et
`src/<package>/adapters/inbound/langgraph/agent.py`. Le projet ne modifie ensuite que ce fichier pour
son agent. Comme `fastapi` et `fastmcp`, LangGraph est configuré par son nom produit dans
`AppConfig.langgraph`, sans `adapters.agent`. L'adapter `observability/langsmith` génère
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
