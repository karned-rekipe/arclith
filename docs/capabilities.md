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

Adapters disponibles:

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

Pour OpenAI et Anthropic, la CLI génère `config/secrets.yaml` avec un resolver `env`, afin que
`adapters.lm.api_key` soit alimenté par `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY` sans écrire la clé
dans `lm.yaml`.

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
  --param model_name=gpt-4o-mini \
  --param api_key="$OPENAI_API_KEY" \
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
