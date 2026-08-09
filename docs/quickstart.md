# Quickstart Arclith

Ce guide montre comment démarrer un projet concret avec Arclith, puis comment le faire évoluer par
adapter sans modifier le code métier.

Arclith doit rester une brique hexagonale stable:

- le domaine et les cas d'usage portent le métier;
- les adapters inbound exposent le métier via API, MCP, bus ou CLI;
- les adapters outbound branchent MongoDB, DuckDB, cache, LLM, tracing ou secrets;
- la CLI assemble ces briques et met a jour la configuration.

## Prérequis

- Python 3.13
- `uv`
- `git`

Installer la CLI depuis le repository:

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
arclith-cli version
```

Pour partir d'un projet vide de métier, utiliser `init`, puis ajouter explicitement les fichiers
du cœur:

```bash
arclith-cli init todo-list-service
cd todo-list-service
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo
```

Pour tester une branche de développement avant merge:

```bash
uv tool install --force "git+https://github.com/karned-rekipe/arclith.git@feat/hexagonal-foundation#subdirectory=cli"
```

## 1. Créer un projet concret

Exemple: un service `pantry-agent` qui gère une entité `Ingredient`.

```bash
mkdir -p ~/Perso/projets/demo
cd ~/Perso/projets/demo

arclith-cli new Ingredient pantry-agent --port 8100
cd pantry-agent
uv sync
```

Le premier `uv sync` crée `uv.lock` pour le projet généré. Ensuite, les commandes
`uv run --frozen ...` peuvent être utilisées pour garantir que l'environnement reste
strictement conforme au lockfile.

Le projet généré suit le layout canonique:

```text
src/pantry_agent/
  domain/
    models/
    ports/
      inbound/
      outbound/
  application/
  adapters/
    inbound/
    outbound/
  infrastructure/
config/
tests/
main.py
```

## 2. Lancer API, MCP et probes

En développement, le mode `all` lance l'API, MCP HTTP et les probes.

```bash
MODE=all uv run --frozen python main.py
```

Par convention:

- API FastAPI: `http://127.0.0.1:8100`
- MCP HTTP: `http://127.0.0.1:8101`
- probes: `http://127.0.0.1:9000`

Vérifier l'état:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:9000/info
```

Créer puis lire une ressource:

```bash
CREATE_RESPONSE=$(curl -fsS -X POST http://127.0.0.1:8100/v1/ingredients/ \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-$(uv run --frozen python -c 'import uuid; print(uuid.uuid4())')" \
  -d '{"name":"Farine de ble"}')

echo "$CREATE_RESPONSE"

INGREDIENT_ID=$(CREATE_RESPONSE="$CREATE_RESPONSE" uv run --frozen python - <<'PY'
import json
import os

print(json.loads(os.environ["CREATE_RESPONSE"])["data"]["uuid"])
PY
)

curl -fsS "http://127.0.0.1:8100/v1/ingredients/$INGREDIENT_ID"
curl -fsS "http://127.0.0.1:8100/v1/ingredients/?name=farine"
```

## 3. Changer ou ajouter un adapter outbound

Pour ajouter seulement du cœur métier, sans CRUD ni adapter automatique :

```bash
arclith-cli add-entity ShoppingItem
arclith-cli add-usecase PlanShoppingList
arclith-cli add-intent-interpreter ShoppingIntent
```

Ces commandes créent des fichiers minimaux dans `src/<package>/domain/models/` et
`src/<package>/domain/ports/inbound/`, `src/<package>/application/use_cases/` ou
`src/<package>/application/intent_interpreters/`. Les champs, invariants et appels aux adapters
restent du code métier à écrire dans le projet.

L'adapter actif est déclaré dans:

```text
config/adapters/adapters.yaml
```

Exemple:

```yaml
logger: console
repository: memory
```

Pour ajouter ou remplacer un adapter de repository:

```bash
arclith-cli capabilities
arclith-cli add-adapter
```

Le wizard détecte les entités dans `src/<package>/domain/models/`, pose les questions nécessaires,
génère les fichiers de l'adapter et met à jour la configuration.

Le même flux peut être joué en mode direct:

```bash
arclith-cli add-adapter --adapter mongodb --entity Ingredient --db-name pantry_agent --yes
arclith-cli add-adapter --adapter duckdb --all-entities --path data/ --no-activate --yes
arclith-cli add-adapter --adapter mariadb --entity Ingredient --param database=pantry_agent --param user=app --yes
```

### MongoDB

Le wizard MongoDB doit produire une configuration scoped:

```text
config/adapters/outbound/mongodb.yaml
```

Exemple attendu:

```yaml
multitenant: false
db_name: pantry_agent
collection_name: ingredients
```

L'URI reste un secret et ne doit pas être commitée. En local, utiliser `secrets.yaml` ou une variable
d'environnement selon la recette active.

### DuckDB

Exemple:

```yaml
multitenant: false
path: data/
```

### MariaDB

Installer l'extra dans le projet qui utilise cet adapter:

```bash
uv add "arclith[mariadb]"
```

Génération directe:

```bash
arclith-cli add-adapter \
  --adapter mariadb \
  --entity Ingredient \
  --param host=127.0.0.1 \
  --param port=3306 \
  --param database=pantry_agent \
  --param user=app \
  --yes
```

Exemple de configuration générée:

```yaml
host: 127.0.0.1
port: 3306
database: pantry_agent
user: app
password: null
driver: asyncmy
table_prefix: ""
multitenant: false
```

Le mot de passe ou l'URL complète doivent rester dans un resolver de secrets, par exemple
`config/secrets.yaml`, `env` ou Vault.

## 4. Ajouter un autre inbound sans toucher au métier

Le même service applicatif peut être exposé par plusieurs adapters:

- FastAPI pour HTTP;
- FastMCP pour les outils MCP;
- un bus plus tard pour RabbitMQ, Kafka ou autre.

La règle à conserver: l'inbound transforme le protocole en appel de cas d'usage. Il ne contient pas
le métier.

## 5. Cas agent IA

Pour un agent, le cœur doit rester testable sans LLM:

```text
Natural language
  -> adapter inbound API / MCP / bus
  -> use case application
  -> intent interpreter port
  -> command / DTO structure
  -> service métier
```

Le LLM est un adapter outbound derrière un port. Il traduit une demande naturelle en données
structurées, mais n'exécute pas directement le métier.

Exemple de ports applicatifs cibles:

- `IntentInterpreterPort`: transforme une phrase en commande structurée;
- `RepositoryPort`: persiste les entités;
- `TracePort`: envoie les traces LangSmith ou autre;
- `EventBusPort`: publie des événements si besoin.

### LangSmith comme banc de test

Arclith ne génère pas d'UI dédiée pour tester un agent. Le chemin standard est un adapter
`agent/langgraph` testé dans LangGraph Studio, avec les traces branchées sur LangSmith:

```bash
uv add "arclith[langgraph]"
arclith-cli add-adapter --capability llm --adapter lmstudio --param "model_name=<model-id-lm-studio>" --yes
arclith-cli add-adapter --capability agent --adapter langgraph
arclith-cli add-adapter --capability observability --adapter langsmith
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

L'adapter `agent/langgraph` génère `langgraph.json`, `config/adapters/inbound/langgraph.yaml` et
`src/<package>/adapters/inbound/langgraph/agent.py`. Le projet n'a plus qu'à modifier ce fichier
pour définir l'état, les nœuds et les transitions de son agent. Comme `fastapi` et `fastmcp`,
LangGraph est configuré par son nom produit dans `AppConfig.langgraph`, sans clé générique
`adapters.agent`.
Le flux attendu est: utilisateur ou canal conversationnel -> LangGraph Agent Server -> `agent.py` ->
ports et use cases applicatifs. Les nodes peuvent utiliser un `LLMPort` configuré par `llm/*` et les
traces via `observability/*`, sans appeler les repositories directement.

L'adapter `observability/langsmith` demande le projet LangSmith, l'endpoint, l'activation du tracing et
`LANGSMITH_API_KEY`. Elle génère `config/adapters/outbound/langsmith.yaml`, ajoute `langsmith` à
`observability.enabled`, met à jour `.env`, et ajoute `.env` au `.gitignore` si besoin.

L'adapter `llm/lmstudio` génère `config/adapters/outbound/lm.yaml`, chargé dans
`AppConfig.adapters.lm`. L'interpréteur d'intention applicatif consomme ensuite un `LLMPort`;
LangGraph ne fait qu'orchestrer les nœuds et injecter l'adapter outbound.

Pour `llm/openai`, choisir explicitement le modèle et garder la clé hors du dépôt: la CLI mappe
`adapters.lm.api_key` vers `OPENAI_API_KEY` via `config/secrets.yaml`, puis la valeur réelle vient de
`.env` local gitignoré, de l'environnement runtime ou d'un resolver Vault.
Utiliser `llm/anthropic` pour Claude via le provider Anthropic; garder `llm/openai` pour OpenAI,
LM Studio ou tout endpoint OpenAI-compatible avec `base_url`.

Le `langgraph.json` généré pointe vers `.env` pour que le serveur local charge les variables LangSmith.
Les tests conversationnels et traces agent se font ensuite dans LangSmith Studio.

Pour un parcours complet depuis un projet vide, avec création d'entité, API FastAPI, adapter
LangGraph, LangSmith et LLM local LM Studio, suivre:

- [Quickstart agent Arclith from scratch](agent-quickstart.md)

## 6. Valider avant commit

```bash
make quality
```

Le sample officiel `_sample` sert de banc de test pour les évolutions Arclith. Avant de publier
Arclith, vérifier aussi:

```bash
cd /Users/killian/Perso/projets/Arclith/_sample
make quality
```

Terminal 1:

```bash
cd /Users/killian/Perso/projets/Arclith/_sample
MODE=all uv run --frozen python main.py
```

Terminal 2:

```bash
cd /Users/killian/Perso/projets/Arclith/_sample
make demo-smoke
```

## Reference

- Sample fonctionnel: `../_sample`
- CLI: `cli/README.md`
- Capacités standardisées: `docs/capabilities.md`
- Architecture: `arclith/docs/architecture.md`
- Decisions: `docs/decisions.md`
