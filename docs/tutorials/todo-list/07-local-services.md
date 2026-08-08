# Annexes locales

Objectif: faire tourner les briques locales utilisées par le service Todo: MongoDB, lecture de la
base, secrets locaux et OpenTelemetry.

![Services locaux autour du Todo service](assets/07-local-services.svg)

## Pourquoi MongoDB ?

Le repository `memory` suffit pour les tests et pour un seul processus Python. MongoDB sert de
stockage partagé quand l'API FastAPI, le serveur MCP et LangGraph tournent dans des processus
séparés.

## Lancer MongoDB avec Docker

Commande minimale:

```bash
docker run --name arclith-mongo   -p 27017:27017   -e MONGO_INITDB_ROOT_USERNAME=arclith   -e MONGO_INITDB_ROOT_PASSWORD=arclith   -v arclith-mongo-data:/data/db   -d mongo:8
```

Vérifier que le container tourne:

```bash
docker ps --filter name=arclith-mongo
docker logs -f arclith-mongo
```

Pour repartir d'une base vide:

```bash
docker rm -f arclith-mongo
docker volume rm arclith-mongo-data
```

La suppression du volume efface uniquement les données MongoDB de ce tutoriel.

## Configurer le repository MongoDB

Installer l'extra:

```bash
uv add "arclith[mongodb]"
```

Ajouter l'adapter:

```bash
arclith-cli add-adapter --capability repository
```

Choisir `mongodb`, puis répondre:

```text
db_name (todo-list-service): todo-list-service
multitenant [y/n] (n): n
Activer mongodb [y/n] (y): y
```

Modifier `config/adapters/adapters.yaml`:

```yaml
logger: console
repository: mongodb
observability:
  enabled:
  - langsmith
```

Modifier `config/adapters/outbound/mongodb.yaml`:

```yaml
multitenant: false   # true = URI + db_name resolus par requete via JWT -> Vault
db_name: todo-list-service   # uri -> secrets.yaml ou Vault (fallback single-tenant)
collection_name: todo
```

Créer `config/secrets.yaml`:

```yaml
resolver: yaml
mappings:
  adapters.mongodb.uri: adapters.mongodb.uri
```

Créer `secrets.yaml` à la racine du projet. Ce fichier reste local:

```yaml
adapters:
  mongodb:
    uri: "mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin"
```

## Adapter MongoDB Todo

Créer les packages:

```bash
mkdir -p src/todo_list_service/adapters/outbound/mongodb/repositories
touch src/todo_list_service/adapters/outbound/mongodb/__init__.py
touch src/todo_list_service/adapters/outbound/mongodb/repositories/__init__.py
```

Créer `src/todo_list_service/adapters/outbound/mongodb/repositories/todo_repository.py`:

```python
from datetime import date
from typing import Any

from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.adapters.outbound.mongodb.repository import MongoDBRepository
from arclith.domain.ports.outbound.logger import Logger
from todo_list_service.domain.models.todo import Todo


class MongoDBTodoRepository(MongoDBRepository[Todo]):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        super().__init__(config, Todo, logger)

    def _to_doc(self, entity: Todo) -> dict[str, Any]:
        doc = super()._to_doc(entity)
        due_date = doc.get("due_date")
        if isinstance(due_date, date):
            doc["due_date"] = due_date.isoformat()
        return doc

    # TODO: add custom query methods here
    # async def find_by_name(self, name: str) -> list[Todo]:
    #     async with self._collection() as col:
    #         return [
    #             self._from_doc(doc)
    #             async for doc in col.find({"name": name, "deleted_at": None})
    #         ]
```

Créer `src/todo_list_service/adapters/outbound/mongodb/repository.py`:

```python
from todo_list_service.adapters.outbound.mongodb.repositories.todo_repository import MongoDBTodoRepository

__all__ = ["MongoDBTodoRepository"]
```

Modifier `src/todo_list_service/infrastructure/containers/todo_container.py`:

```python
from __future__ import annotations

from weakref import WeakKeyDictionary

from arclith import Arclith
from arclith.domain.ports.outbound.repository import Repository

from todo_list_service.adapters.outbound.mongodb.repositories.todo_repository import MongoDBTodoRepository
from todo_list_service.application.use_cases.create_todo import CreateTodoUseCase
from todo_list_service.application.use_cases.list_todos import ListTodosUseCase
from todo_list_service.domain.models.todo import Todo
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort

_repositories: WeakKeyDictionary[Arclith, Repository[Todo]] = WeakKeyDictionary()


def build_todo_repository(app: Arclith) -> Repository[Todo]:
    repository = _repositories.get(app)
    if repository is None:
        repository = _create_todo_repository(app)
        _repositories[app] = repository
    return repository


def _create_todo_repository(app: Arclith) -> Repository[Todo]:
    if app.config.adapters.repository == "mongodb":
        return MongoDBTodoRepository(app.config.adapters.mongodb, app.logger)
    return app.repository(Todo)


def clear_todo_repository_cache() -> None:
    _repositories.clear()


def build_create_todo_use_case(app: Arclith) -> CreateTodoPort:
    return CreateTodoUseCase(build_todo_repository(app))


def build_list_todos_use_case(app: Arclith) -> ListTodosPort:
    return ListTodosUseCase(build_todo_repository(app))
```

Le container choisit `MongoDBTodoRepository` quand `repository: mongodb` est actif. Sinon, il utilise
le repository standard Arclith, ce qui permet aux tests de rester en `memory`.

## Pyproject complet

Les commandes `uv add` des étapes API, MCP, agent et MongoDB donnent ce `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "todo-list-service"
version = "0.1.0"
description = "Arclith service"
requires-python = ">=3.13"
dependencies = [
    "arclith[fastapi,langgraph,mcp,mongodb]>=0.15.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/todo_list_service"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=9.0.0",
    "pytest-asyncio>=1.3.0",
    "httpx>=0.27.0",
]
```

`uv.lock` est généré par `uv sync`; il n'est pas recopié à la main dans le tutoriel.

## Relancer API, MCP et LangGraph

Lancer chaque canal dans son terminal.

API:

```bash
MODE=api uv run python main.py
```

MCP:

```bash
MODE=mcp_http uv run python main.py
```

LangGraph:

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

À partir de là, une todo créée par Swagger, par LM Studio via MCP ou par LangGraph doit être visible
par les autres canaux.

## Visualiser MongoDB avec Compass

Connexion:

```text
mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin
```

À vérifier:

- base: `todo-list-service`;
- collection: `todo`;
- documents: un document par todo, avec `_id` égal à l'UUID public de l'entité.

## Requêter MongoDB en CLI

Installer `mongosh` si nécessaire, puis:

```bash
mongosh "mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin"
```

Dans le shell:

```javascript
show collections
db.todo.find().pretty()
db.todo.countDocuments({ deleted_at: null })
```

## Ajouter OpenTelemetry localement

LangSmith observe surtout les runs LLM et LangGraph. OpenTelemetry sert à tracer le service comme un
microservice classique: requêtes HTTP, spans, latences et erreurs techniques.

Pour un labo local, Jaeger all-in-one suffit:

```bash
docker run --rm --name arclith-jaeger   -p 16686:16686   -p 4317:4317   -p 4318:4318   -p 5778:5778   -p 9411:9411   -d cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
```

Ouvrir ensuite:

```text
http://127.0.0.1:16686
```

Ajouter l'adapter OpenTelemetry:

```bash
uv add "arclith[opentelemetry]"
arclith-cli add-adapter --capability observability
```

Choisir `opentelemetry`, puis utiliser un endpoint OTLP HTTP local:

```text
endpoint: http://127.0.0.1:4318
service_name: todo-list-service
```

Relancer l'API, appeler Swagger ou `curl`, puis chercher le service `todo-list-service` dans Jaeger.

## LangSmith ou OpenTelemetry ?

Les deux sont complémentaires:

| Besoin | Outil |
| --- | --- |
| comprendre les messages envoyés au modèle | LangSmith |
| voir pourquoi l'agent repose une question | LangSmith Studio |
| mesurer les appels HTTP et les erreurs techniques | OpenTelemetry |
| corréler plusieurs microservices | OpenTelemetry |

Pour ce tutoriel, LangSmith aide à apprendre l'agent. OpenTelemetry prépare la suite production.

## Tout valider

```bash
uv sync
uv run python -m pytest
```

Résultat attendu:

```text
26 passed
```

Étape précédente: [ajouter un agent](06-agent.md).
