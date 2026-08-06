# Quickstart Arclith

Ce guide montre comment demarrer un projet concret avec Arclith, puis comment le faire evoluer par adapter sans modifier le code metier.

Arclith doit rester une brique hexagonale stable:

- le domaine et les cas d'usage portent le metier;
- les adapters inbound exposent le metier via API, MCP, bus ou CLI;
- les adapters outbound branchent MongoDB, DuckDB, cache, LLM, tracing ou secrets;
- la CLI assemble ces briques et met a jour la configuration.

## Prerequis

- Python 3.13
- `uv`
- `git`

Installer la CLI depuis le repository:

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
arclith-cli version
```

Pour tester une branche de developpement avant merge:

```bash
uv tool install --force "git+https://github.com/karned-rekipe/arclith.git@feat/hexagonal-foundation#subdirectory=cli"
```

## 1. Creer un projet concret

Exemple: un service `pantry-agent` qui gere une entite `Ingredient`.

```bash
mkdir -p ~/Perso/projets/demo
cd ~/Perso/projets/demo

arclith-cli new Ingredient pantry-agent --port 8100
cd pantry-agent
uv sync
```

Le premier `uv sync` cree `uv.lock` pour le projet genere. Ensuite, les commandes
`uv run --frozen ...` peuvent etre utilisees pour garantir que l'environnement reste
strictement conforme au lockfile.

Le projet genere suit le layout canonique:

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

En developpement, le mode `all` lance l'API, MCP HTTP et les probes.

```bash
MODE=all uv run --frozen python main.py
```

Par convention:

- API FastAPI: `http://127.0.0.1:8100`
- MCP HTTP: `http://127.0.0.1:8101`
- probes: `http://127.0.0.1:9000`

Verifier l'etat:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:9000/info
```

Creer puis lire une ressource:

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

Pour ajouter seulement du coeur metier, sans CRUD ni adapter automatique:

```bash
arclith-cli add-entity ShoppingItem
arclith-cli add-usecase PlanShoppingList
```

Ces commandes creent des fichiers minimaux dans `src/<package>/domain/models/` et
`src/<package>/application/use_cases/`. Les champs, invariants, ports et appels aux adapters restent
du code metier a ecrire dans le projet.

L'adapter actif est declare dans:

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

Le wizard detecte les entites dans `src/<package>/domain/models/`, pose les questions necessaires, genere les fichiers de l'adapter et met a jour la configuration.

Le meme flux peut etre joue en mode direct:

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

L'URI reste un secret et ne doit pas etre commitee. En local, utiliser `secrets.yaml` ou une variable d'environnement selon la recette active.

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

Generation directe:

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

Exemple de configuration generee:

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

Le mot de passe ou l'URL complete doivent rester dans un resolver de secrets, par exemple `config/secrets.yaml`, `env` ou Vault.

## 4. Ajouter un autre inbound sans toucher au metier

Le meme service applicatif peut etre expose par plusieurs adapters:

- FastAPI pour HTTP;
- FastMCP pour les outils MCP;
- un bus plus tard pour RabbitMQ, Kafka ou autre.

La regle a conserver: l'inbound transforme le protocole en appel de cas d'usage. Il ne contient pas le metier.

## 5. Cas agent IA

Pour un agent, le coeur doit rester testable sans LLM:

```text
Natural language
  -> adapter inbound API / MCP / bus
  -> use case application
  -> planner port
  -> command / DTO structure
  -> service metier
```

Le LLM est un adapter outbound derriere un port. Il traduit une demande naturelle en donnees structurees, mais n'execute pas directement le metier.

Exemple de ports applicatifs cibles:

- `PlannerPort`: transforme une phrase en commande structuree;
- `RepositoryPort`: persiste les entites;
- `TracePort`: envoie les traces LangSmith ou autre;
- `EventBusPort`: publie des evenements si besoin.

### LangSmith comme banc de test

Arclith ne genere pas d'UI dediee pour tester un agent. Le chemin standard est un adapter
`agent/langgraph` teste dans LangGraph Studio, avec les traces branchees sur LangSmith:

```bash
uv add "arclith[langgraph]"
arclith-cli add-adapter --capability agent --adapter langgraph
arclith-cli add-adapter --capability observability --adapter langsmith
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

L'adapter `agent/langgraph` genere `langgraph.json`, `config/adapters/inbound/langgraph.yaml` et
`src/<package>/adapters/inbound/langgraph/agent.py`. Le projet n'a plus qu'a modifier ce fichier
pour definir l'etat, les noeuds et les transitions de son agent. Comme `fastapi` et `fastmcp`,
LangGraph est configure par son nom produit dans `AppConfig.langgraph`, sans cle generique
`adapters.agent`.

L'adapter `observability/langsmith` demande le projet LangSmith, l'endpoint, l'activation du tracing et
`LANGSMITH_API_KEY`. Elle genere `config/adapters/outbound/langsmith.yaml`, met a jour `.env`,
et ajoute `.env` au `.gitignore` si besoin.

Le `langgraph.json` genere pointe vers `.env` pour que le serveur local charge les variables LangSmith.
Les tests conversationnels et traces agent se font ensuite dans LangSmith Studio.

Pour un parcours complet depuis un projet vide, avec creation d'entite, API FastAPI, adapter
LangGraph, LangSmith et LLM local LM Studio, suivre:

- [Quickstart agent Arclith from scratch](agent-quickstart.md)

## 6. Valider avant commit

```bash
make quality
```

Le sample officiel `_sample` sert de banc de test pour les evolutions Arclith. Avant de publier Arclith, verifier aussi:

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
- Capacites standardisees: `docs/capabilities.md`
- Architecture: `arclith/docs/architecture.md`
- Decisions: `docs/decisions.md`
