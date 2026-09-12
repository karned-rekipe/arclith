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

Installer au préalable la CLI publiée sur PyPI :

```bash
uv tool install arclith-cli
arclith-cli version
```

Pour le parcours recommandé dans un terminal, lancer simplement :

```bash
arclith-cli
```

Le guide persistant demande le résultat attendu, montre le plan complet avant
toute écriture et continue dans le nouveau projet. Il couvre le socle minimal,
l'API REST CRUD ou ciblée, FastMCP, LangGraph et RabbitMQ, sans rendre implicite
le choix du repository ou du transport. Voir le
[guide interactif Arclith CLI](cli-guide.md).

Les commandes ci-dessous restent l'équivalent direct pour les scripts et la CI.

Pour partir d'un projet vide de métier, utiliser `init`, puis ajouter explicitement les fichiers
du cœur:

```bash
arclith-cli init todo-list-service
cd todo-list-service
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability api --adapter fastapi --param port=8765 --yes
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
```

`init` n'installe aucun transport. La commande `add-adapter` ci-dessus ajoute le
blueprint et l'extra FastAPI à la demande ; utiliser `mcp/fastmcp` de la même
manière uniquement si le service expose aussi MCP. Pour un CRUD, utiliser plutôt
ce parcours complet, en alternative au bloc précédent :

```bash
arclith-cli init todo-list-service
cd todo-list-service
arclith-cli add-entity Todo --profile crud
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

Le profil crée le cœur applicatif ; `expose-feature` constitue la décision
séparée qui publie ses cinq opérations sur l'adapter déjà installé. Consulter le
[blueprint CRUD](blueprints/crud.md) pour le contrat HTTP et ses erreurs.

Chaque commande mutante réussie enrichit `arclith.recipe.yaml`. Ce fichier
versionné conserve les décisions de scaffolding sans remplacer Git et sans
stocker de secret. Consulter la timeline avec `arclith-cli history`, puis lire
le guide [Recettes Arclith CLI](cli-recipe.md) pour le dry-run et le replay.

Pour tester une branche de développement avant merge:

```bash
uv tool install --force "git+https://github.com/karned-rekipe/arclith.git@feat/hexagonal-foundation#subdirectory=cli"
```

## 1. Comprendre le raccourci `new`

Pour compatibilité, `new` reste disponible. Il équivaut à `init` suivi de
`add-entity`; il ne télécharge plus un projet complet et n'ajoute aucun adapter.
Le mode interactif demande le profil applicatif après l'entité ; le mode direct
peut utiliser `--profile crud`, sinon il reste `minimal`.

```bash
mkdir -p ~/Perso/projets/demo
cd ~/Perso/projets/demo

arclith-cli new Ingredient pantry-agent --port 8100
cd pantry-agent
uv sync
```

L'option `--port` ne démarre et ne configure aucun serveur : elle sert uniquement
à afficher la commande FastAPI suggérée. Le transport reste une décision explicite
avec `add-adapter`.

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

Le premier `uv sync` crée `uv.lock`. Ensuite, ajouter les use cases et uniquement
les adapters nécessaires en suivant les parcours dédiés :

- [API FastAPI](quickstarts/api.md)
- [MCP FastMCP](quickstarts/mcp.md)
- [command bus RabbitMQ](quickstarts/bus.md)
- [repositories](capabilities/repository.md)

## 2. Changer ou ajouter un adapter outbound

Pour ajouter seulement du cœur métier, sans CRUD ni adapter automatique :

```bash
arclith-cli add-entity ShoppingItem
arclith-cli add-usecase PlanShoppingList --entity ShoppingItem
arclith-cli add-usecase RunMaintenance --no-entity
arclith-cli add-intent-interpreter ShoppingIntent
```

Pour le cycle de vie CRUD classique, sans adapter automatique :

```bash
arclith-cli add-entity ShoppingItem --profile crud
# ou, si l'entité existe déjà
arclith-cli add-blueprint crud --entity ShoppingItem
```

Puis, uniquement si une API REST est voulue :

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature shopping_item --via fastapi \
  --path /v1/shopping-items
```

`add-entity` ajoute un squelette guidé sans import inutilisé. `add-usecase`
propose les entités détectées en interactif ; en mode direct, `--entity`,
`--new-entity` et `--no-entity` rendent le choix explicite et sont mutuellement
exclusifs. Les fichiers générés montrent le pattern
`Command/Query -> UseCase -> Entity/Result`, mais les champs, invariants et
appels aux ports restent du code métier à écrire dans le projet. Lire le
[deep dive scaffold CLI](deep-dives/cli-scaffold.md) pour les exemples complets,
ou la [vue d'ensemble des blueprints applicatifs](blueprints.md) pour comprendre
la séparation entre comportement, capability et adapter.

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
arclith-cli capabilities --json
arclith-cli add-adapter
```

La sortie JSON expose les garanties de chaque adapter repository. Utiliser la
[matrice de choix repository](capabilities/repository.md) pour comparer runtime,
multi-processus, transactions, stratégie de schéma, usages et limites avant de
modifier l'adapter actif.

Le wizard détecte les entités dans `src/<package>/domain/models/`, pose les questions nécessaires,
génère les fichiers de l'adapter et met à jour la configuration.

Le même flux peut être joué en mode direct:

```bash
arclith-cli add-adapter --capability repository --adapter mongodb --db-name pantry_agent --yes
arclith-cli add-adapter --capability repository --adapter duckdb --path data/ --no-activate --yes
arclith-cli add-adapter --capability repository --adapter mariadb \
  --param database=pantry_agent --param user=app --yes
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

La CLI ajoute elle-même l'extra `arclith[mariadb]` au projet.

Génération directe:

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mariadb \
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

## 3. Ajouter un autre inbound sans toucher au métier

Le même service applicatif peut être exposé par plusieurs adapters:

- FastAPI pour HTTP;
- FastMCP pour les outils MCP;
- `command-bus/rabbitmq` pour un worker RabbitMQ.

La règle à conserver: l'inbound transforme le protocole en appel de cas d'usage. Il ne contient pas
le métier.

## 4. Cas agent IA

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

### LangGraph local comme banc de test

Arclith ne génère pas d'UI dédiée pour tester un agent. Le chemin standard est un adapter
`agent/langgraph` testé via l'Agent Server local. LangGraph Studio et LangSmith sont utiles pour
inspecter les conversations quand internet et la clé sont disponibles, mais ils ne sont pas requis
pour valider un run local:

```bash
uv add "arclith[langgraph]"
arclith-cli add-adapter --capability llm --adapter lmstudio --param "model_name=<model-id-lm-studio>" --yes
arclith-cli add-adapter --capability agent --adapter langgraph
export LANGGRAPH_CLI_NO_ANALYTICS=1
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Ajouter LangSmith séparément uniquement lorsque les traces distantes sont souhaitées:

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --profile development \
  --yes
export LANGSMITH_API_KEY="<secret>"
```

Tester sans Studio:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"agent","input":{"messages":[{"role":"human","content":"ping"}]},"stream_mode":"values"}'
```

Pour les commandes complètes LM Studio, threads et inspection de state, lire
[Validation IA locale](learning/local-ai-validation.md).

L'adapter `agent/langgraph` génère `langgraph.json`, `config/adapters/inbound/langgraph.yaml` et
`src/<package>/adapters/inbound/langgraph/agent.py`. Le projet n'a plus qu'à modifier ce fichier
pour définir l'état, les nœuds et les transitions de son agent. Comme `fastapi` et `fastmcp`,
LangGraph est configuré par son nom produit dans `AppConfig.langgraph`, sans clé générique
`adapters.agent`.
Le flux attendu est: utilisateur ou canal conversationnel -> LangGraph Agent Server -> `agent.py` ->
ports et use cases applicatifs. Les nodes peuvent utiliser un `LLMPort` configuré par `llm/*` et les
traces via `observability/*`, sans appeler les repositories directement.

L'adapter `observability/langsmith` génère `config/adapters/outbound/langsmith.yaml`, ajoute
`langsmith` à `observability.enabled`, ajoute l'extra optionnel correspondant et écrit uniquement
les valeurs non secrètes dans `.env.example`. La CLI ne demande et n'écrit jamais la clé API.
Définir `LANGSMITH_API_KEY` dans l'environnement runtime ou un secret manager avant de lancer un
service avec cet adapter activé. Sans LangSmith, ne pas l'ajouter à `observability.enabled`: aucun
client, buffer ou appel réseau n'est alors créé.

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

## 5. Construire l'image runtime

`init` et `new` n'incluent aucun fichier Docker. Ajouter explicitement le runtime lorsque le service
doit être conteneurisé :

```bash
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
uv lock
docker build -t pantry-agent:local .
```

La même image démarre les transports par argument:

```bash
docker run --rm -p 8100:8100 -p 9000:9000 pantry-agent:local api
docker run --rm -p 8101:8101 -p 9000:9000 pantry-agent:local mcp_http
docker run --rm --env ARCLITH_RUNTIME_MODE=all -p 8100:8100 -p 8101:8101 -p 9000:9000 pantry-agent:local
```

Pour `bus`, ajouter d'abord `command-bus/rabbitmq` et implémenter le runner `MODE=bus` dans
`main.py`. Pour `agent`, ajouter `agent/langgraph`; `arclith-run agent` utilise `langgraph.json` ou
`ARCLITH_AGENT_COMMAND`.

Les secrets restent hors image: utiliser l'environnement runtime, Docker secrets, Vault ou fichiers
montés. Le `.dockerignore` généré exclut `.env`, `secrets.yaml` et les clés privées.

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
- Tutoriel Docker: `docs/runtime-docker.md`
- Architecture: `arclith/docs/architecture.md`
- Decisions: `docs/decisions.md`
