# 1. Initialiser le projet

Objectif: créer le projet Arclith minimal, installer les dépendances et préparer les fichiers de base
qui resteront dans le dépôt.

![Capture interactive init](assets/01-init-project.svg)

Depuis le dossier qui contiendra les projets de test:

```bash
mkdir -p ~/Perso/projets/demo-arclith
cd ~/Perso/projets/demo-arclith

uv tool upgrade arclith-cli
arclith-cli init
```

Répondre au prompt:

```text
Projet (ex : my-recipe-service, meal-planner)
  Nom du projet: todo-list-service
```

Entrer dans le projet et installer les dépendances:

```bash
cd todo-list-service
uv sync
```

Le projet démarre avec `repository: memory`:

```yaml
# config/adapters/adapters.yaml
logger: console
repository: memory
observability:
  enabled: []
```

## Fichiers de base

Vérifier ou créer `.gitignore`:

```text
.DS_Store
.idea/
.langgraph_api/
.playwright-cli/
__pycache__/
*.py[cod]
.venv/
.env
/secrets.yaml
.coverage
htmlcov/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
```

Créer `README.md`:

````markdown
# Arclith POC Todo

POC Arclith montrant qu'un même coeur applicatif peut être exposé par FastAPI, FastMCP et LangGraph.

## Ce que le POC démontre

- `Todo`, `CreateTodoPort` et `ListTodosPort` restent dans le coeur métier.
- FastAPI adapte HTTP vers les ports inbound.
- FastMCP expose les mêmes use cases sous forme de tools MCP.
- LangGraph orchestre une conversation, mais appelle les mêmes ports que l'API et le MCP.
- Les intent-interpreters séparent la classification d'action (`TodoActionInterpreter`) de
  l'extraction de champs (`TodoConversationInterpreter`).
- Le runtime utilise MongoDB pour partager les données entre processus.
- Les tests utilisent une config `memory` temporaire pour rester rapides et déterministes.

## Installer

```bash
uv sync
uv run python -m pytest
```

## Lancer les tests

```bash
uv run python -m pytest
```

La suite de tests copie `config/` dans un dossier temporaire et remplace `repository: mongodb` par
`repository: memory`. Cela permet de tester le coeur, le MCP et l'agent sans démarrer MongoDB.

## Configurer MongoDB pour le runtime

`config/secrets.yaml` déclare le mapping attendu. Créez un fichier local `secrets.yaml` à la racine:

```yaml
adapters:
  mongodb:
    uri: "mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin"
```

Ce fichier est ignoré par Git.

## Lancer l'API

```bash
MODE=api uv run python main.py
```

Swagger:

```text
http://127.0.0.1:8120/docs
```

## Lancer le MCP

```bash
MODE=mcp_http uv run python main.py
```

Endpoint MCP:

```text
http://127.0.0.1:8121/mcp
```

## Lancer LangGraph

LM Studio doit exposer un serveur OpenAI-compatible sur `http://127.0.0.1:1234/v1`.

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Le graphe est déclaré dans `langgraph.json`:

```text
todo_agent -> src/todo_list_service/adapters/inbound/langgraph/agent.py:agent
```

Si Studio n'est pas accessible, ouvrir l'API locale:

```text
http://127.0.0.1:2024/docs
```

Les commandes `curl` de validation offline sont regroupées dans
[Validation IA locale et hors ligne](../../learning/local-ai-validation.md).

## Découpage principal

```text
domain/models/todo.py
domain/ports/inbound/create_todo.py
domain/ports/inbound/list_todos.py
application/use_cases/create_todo.py
application/use_cases/list_todos.py
application/intent_interpreters/
adapters/inbound/fastapi/
adapters/inbound/fastmcp/
adapters/inbound/langgraph/
adapters/outbound/mongodb/
infrastructure/containers/todo_container.py
```

Le container est le seul endroit qui choisit le repository concret. Les adapters inbound ne parlent
qu'aux ports applicatifs.
````

La configuration applicative créée par le scaffold contient les fichiers suivants.

`config/app.yaml`:

```yaml
name: todo-list-service
version: "0.1.0"
description: "todo-list-service — built with Arclith"
```

`config/http.yaml`:

```yaml
idempotency:
  enabled: true
  ttl_seconds: 86400
  required: false

etag:
  enabled: true

cache_control:
  get_single_max_age: 300
  get_list_max_age: 60
```

`config/soft_delete.yaml`:

```yaml
retention_days: 30
```

`config/adapters/inbound/probe.yaml`:

```yaml
host: 0.0.0.0
port: 9000
enabled: true
```

Créer le marqueur de typage Python:

```bash
touch src/todo_list_service/py.typed
```

Les fichiers `__init__.py` vides sont conservés dans les packages pour garder des imports explicites:

```bash
touch src/todo_list_service/__init__.py
touch src/todo_list_service/adapters/__init__.py
touch src/todo_list_service/adapters/inbound/__init__.py
touch src/todo_list_service/adapters/outbound/__init__.py
touch src/todo_list_service/application/__init__.py
touch src/todo_list_service/domain/__init__.py
touch src/todo_list_service/domain/models/__init__.py
touch src/todo_list_service/domain/ports/__init__.py
touch src/todo_list_service/domain/ports/inbound/__init__.py
touch src/todo_list_service/domain/ports/outbound/__init__.py
touch src/todo_list_service/infrastructure/__init__.py
touch src/todo_list_service/infrastructure/containers/__init__.py
touch tests/__init__.py
```

Les sous-packages créés dans les étapes API, MCP, LangGraph et MongoDB ajoutent leurs propres
`__init__.py` avec la même règle: fichier vide quand aucun export n'est utile, fichier explicite
quand un import public doit être stabilisé.

## Tester

Le scaffold minimal contient un test de bootstrap. Il sera ajusté dans l'étape MCP pour utiliser une
configuration `memory` temporaire.

```bash
uv run python -m pytest
```

## Voie rapide

```bash
uv tool upgrade arclith-cli
arclith-cli init todo-list-service
cd todo-list-service
uv sync
uv run python -m pytest
```

Étape suivante: [créer l'entité Todo](02-create-entity.md).
