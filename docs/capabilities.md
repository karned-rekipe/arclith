# Capacites standardisees

Arclith doit fournir une base stable pour assembler rapidement des services hexagonaux. La CLI s'appuie donc sur un catalogue de capacites plutot que sur des chemins codes au cas par cas.

## Principe

Une capacite decrit:

- le role architectural expose par la CLI;
- le layer hexagonal concerne, `inbound` ou `outbound`;
- les adapters disponibles;
- les parametres requis par adapter;
- le chemin de configuration;
- la cle d'activation dans `config/adapters/adapters.yaml`, quand la capacite a besoin d'un
  selecteur actif.

Le code metier reste dans `domain/` et `application/`. Les capacites ne doivent generer que du cablage, des ports, des schemas ou des adapters autour de ce coeur.

## Catalogue actuel

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

### `repository`

Capacite outbound pour la persistance des entites metier derriere un port repository.

Adapters disponibles:

- `memory`: stockage volatile pour dev, tests et smoke locaux;
- `mongodb`: repository async MongoDB, single-tenant ou multitenant;
- `duckdb`: repository fichier local pour SQL analytique et demos sans serveur;
- `mariadb`: repository MariaDB async optionnel, avec stockage generique JSON par entite.

Activation:

```yaml
repository: mongodb
```

### `api`

Capacite inbound pour exposer les cas d'usage via HTTP REST.

Adapter disponible:

- `fastapi`: application FastAPI configuree par `Arclith.fastapi()`.

Configuration runtime:

```yaml
# config/adapters/inbound/fastapi.yaml
host: 0.0.0.0
port: 8000
reload: true
```

Cette capacite n'a pas de cle d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/inbound/fastapi.yaml` est charge directement dans `AppConfig.api`.

### `mcp`

Capacite inbound pour exposer les cas d'usage via MCP.

Adapter disponible:

- `fastmcp`: serveur FastMCP configure par `Arclith.fastmcp()`, `run_mcp_sse()` et
  `run_mcp_http()`.

Configuration runtime:

```yaml
# config/adapters/inbound/fastmcp.yaml
host: 127.0.0.1
port: 8001
```

Cette capacite n'a pas de cle d'activation dans `config/adapters/adapters.yaml`: le chemin
`config/adapters/inbound/fastmcp.yaml` est charge directement dans `AppConfig.mcp`.

### `observability`

Capacite outbound pour brancher l'observabilite et le banc de test agent.

Adapters disponibles:

- `langsmith`: tracing LangSmith et execution locale dans LangGraph Studio;
- `opentelemetry`: export OTLP traces/metrics et instrumentation FastAPI.

Activation:

```yaml
observability: langsmith
# ou
observability: opentelemetry
```

Arclith considere LangSmith Studio comme l'endroit standard pour tester un agent. Le serveur local
LangGraph doit lire `.env` via `langgraph.json`; `.env` contient `LANGSMITH_API_KEY`,
`LANGSMITH_TRACING`, `LANGSMITH_PROJECT` et `LANGSMITH_ENDPOINT`. La cle reste locale et ne doit pas
etre commitee.

OpenTelemetry se configure avec:

```yaml
# config/adapters/outbound/opentelemetry.yaml
enabled: true
service_name: "my-service"
endpoint: "http://localhost:4318"
protocol: "http/protobuf"
headers_env: OTEL_EXPORTER_OTLP_HEADERS
traces: true
metrics: false
instrument_fastapi: true
metrics_export_interval_millis: 60000
```

Installer l'extra avant d'activer l'adapter:

```bash
uv add "arclith[opentelemetry]"
```

### `agent`

Capacite inbound pour exposer les cas d'usage metier via un runtime agent.

Adapter disponible:

- `langgraph`: entrypoint LangGraph Studio base sur la tuyauterie Arclith.

Configuration runtime:

L'adapter `langgraph` suit la convention produit des adapters inbound comme `fastapi` et `fastmcp`:
`config/adapters/inbound/langgraph.yaml` est charge dans `AppConfig.langgraph`. Il n'ajoute pas de
cle generique `adapters.agent` dans `config/adapters/adapters.yaml`.

L'adapter genere:

- `langgraph.json`;
- `config/adapters/inbound/langgraph.yaml`;
- `src/<package>/adapters/inbound/langgraph/agent.py`.

Le fichier `agent.py` est le seul point a modifier pour un nouveau projet agent: l'etat, les noeuds,
les transitions et les appels aux cas d'usage applicatifs. Arclith garde le cablage recurrent:
chargement de configuration, creation du `StateGraph`, compilation, entrypoint Studio et lecture de
`.env`.

## Ajouter un adapter

Le chemin standard est:

```bash
arclith-cli add-adapter --capability repository --adapter mongodb --entity Ingredient --yes
```

Les parametres d'adapter peuvent etre fournis de maniere generique:

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

En mode interactif, la CLI demande aussi `LANGSMITH_API_KEY` et l'ecrit dans `.env`. Le mode direct
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

## Regle d'evolution

Chaque nouvelle capacite doit d'abord etre ajoutee au catalogue, puis consommee par la CLI. Cela garde les futures briques, par exemple MariaDB, bus, planner LLM, tracing ou observability, declaratives et testables.

Une capacite ne doit pas introduire de dependance du core vers un adapter. Elle doit uniquement generer ou cabler les elements externes necessaires.

Les secrets ne doivent pas etre generes dans les fichiers d'adapter. Pour MariaDB, mapper `adapters.mariadb.password` ou `adapters.mariadb.url` via `config/secrets.yaml`, un resolver `env` ou Vault.
