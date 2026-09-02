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
export LANGSMITH_TRACING=false
export LANGGRAPH_CLI_NO_ANALYTICS=1
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

À partir de là, une todo créée par Swagger, par LM Studio via MCP ou par LangGraph doit être visible
par les autres canaux.

## Valider LangGraph Hors Ligne

Studio est utile pour apprendre le graphe, mais l'UI hébergée n'est pas nécessaire. Hors ligne,
tester l'Agent Server local par API:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "todo_agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Quelles sont mes tâches en cours ?"}
      ]
    },
    "stream_mode": "values"
  }'
```

Pour prouver la persistance de conversation, créer un thread:

```bash
THREAD_ID=$(curl -fsS -X POST "http://127.0.0.1:2024/threads" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

curl -N -X POST "http://127.0.0.1:2024/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"todo_agent","input":{"messages":[{"role":"human","content":"Quelles sont mes tâches en cours ?"}]},"stream_mode":"values"}'

curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
```

Les données métier doivent venir de MongoDB via `TodoRepositoryPort`, pas de la mémoire interne du
processus LangGraph.

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

## Ajouter Vault localement

Cette section remplace le fichier local `secrets.yaml` par un Vault de développement. Le mode dev
conserve tout en mémoire, démarre déjà initialisé et non scellé, et utilise un token racine : il est
adapté uniquement à ce POC local, jamais à la production.

### Démarrer Vault en mode dev

Choisir un token jetable dans le terminal courant. La valeur ci-dessous n'est pas un credential réel
et ne doit pas être réutilisée ailleurs :

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=arclith-dev-only

docker run --rm --name arclith-vault \
  -p 127.0.0.1:8200:8200 \
  -e VAULT_DEV_ROOT_TOKEN_ID="$VAULT_TOKEN" \
  -e VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200 \
  -d hashicorp/vault:2.1.0 server -dev
```

Attendre au maximum 30 secondes que le serveur soit disponible :

```bash
for attempt in $(seq 1 30); do
  curl -fsS "$VAULT_ADDR/v1/sys/health" >/dev/null && break
  if [ "$attempt" -eq 30 ]; then
    docker logs arclith-vault
    exit 1
  fi
  sleep 1
done
```

Le binding `127.0.0.1` évite d'exposer le port dev sur le réseau local. Le token est transmis au
container uniquement pour ce lancement jetable ; ne pas le mettre dans Git, dans une image ou dans
un environnement partagé.

### Initialiser KV v2 et les données du POC

Télécharger le [script de seed vérifié](scripts/seed-vault.sh), le placer dans le projet Todo sous
`scripts/seed-vault.sh`, puis l'exécuter :

```bash
mkdir -p scripts
export ARCLITH_REF="${ARCLITH_REF:-main}"
curl -fsSLo scripts/seed-vault.sh \
  "https://raw.githubusercontent.com/karned-rekipe/arclith/${ARCLITH_REF}/docs/tutorials/todo-list/scripts/seed-vault.sh"
chmod +x scripts/seed-vault.sh
./scripts/seed-vault.sh
```

`ARCLITH_REF` peut désigner le tag ou le SHA correspondant à la version de cette documentation afin
de conserver un POC reproductible. Sa valeur par défaut, `main`, convient pour suivre la version de
développement courante.

Le script active le mount `kv` en KV v2 s'il n'existe pas. S'il existe déjà dans une autre version,
le script échoue explicitement au lieu de poursuivre avec des routes incompatibles. Il écrit ensuite
deux entrées de démonstration :

| Chemin | Consommateur | Forme attendue |
| --- | --- | --- |
| `kv/apps/todo-list/mongodb` | `VaultSecretAdapter` | champ unique `value` |
| `kv/rekipe/tenants/client-a` | `VaultTenantResolver` | champs `uri` et `db_name` |

Il peut être rejoué : les mêmes valeurs sont réécrites dans une nouvelle version KV. Pour un POC
strictement hors ligne, copier le contenu affiché ci-dessous au lieu de le télécharger :

```bash
--8<-- "docs/tutorials/todo-list/scripts/seed-vault.sh"
```

### Résoudre le secret applicatif

Installer l'extra Vault, puis remplacer le resolver YAML de la section MongoDB par la capability CLI
`secrets/vault` :

```bash
uv add "arclith[vault]"
arclith-cli add-adapter \
  --capability secrets \
  --adapter vault \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/todo-list/mongodb \
  --param addr=http://127.0.0.1:8200 \
  --param mount=kv \
  --yes
```

Le fichier versionné `config/secrets.yaml` ne contient que le resolver et le mapping :

```yaml
resolver: vault
vault:
  addr: http://127.0.0.1:8200
  mount: kv
mappings:
  adapters.mongodb.uri: apps/todo-list/mongodb
```

Prouver que le service Arclith charge le secret sans afficher sa valeur :

```bash
uv run python - <<'PY'
from arclith import Arclith

runtime = Arclith("config")
mongodb = runtime.config.adapters.mongodb
assert mongodb is not None and mongodb.uri
print("Secret applicatif MongoDB résolu par Vault")
PY
```

Lancer ensuite le service avec la même configuration ; son bootstrap effectue la même résolution :

```bash
MODE=api uv run python main.py
```

Dans un autre terminal, `curl -fsS "http://127.0.0.1:8120/v1/todos/?page=1&per_page=20"`
doit répondre sans erreur de secret. MongoDB doit toujours être démarré comme indiqué au début de
cette page.

`VaultSecretAdapter` intervient une fois au chargement de la configuration. Le chemin mappé doit
exposer un champ `value`; il convient aux secrets partagés par l'instance du service.

### Résoudre des coordonnées par tenant

Cette sous-partie requiert elle aussi l'extra `arclith[vault]`. L'installer si la sous-partie
précédente n'a pas été suivie, puis configurer séparément `tenant/vault` avec le catalogue CLI
courant :

```bash
uv add "arclith[vault]"
arclith-cli add-adapter \
  --capability tenant \
  --adapter vault \
  --param addr=http://127.0.0.1:8200 \
  --param mount=kv \
  --param path_prefix=rekipe/tenants \
  --param tenant_claim=tenant_id \
  --param tenant_uri_ttl=300 \
  --yes
```

Dans une API multitenant complète, le pipeline d'authentification extrait `tenant_id` d'un JWT signé
et appelle le resolver. Pour vérifier ici le contrat Vault sans ajouter de logique métier ni simuler
un JWT, appeler directement le port avec l'identifiant de démonstration :

```bash
uv run python - <<'PY'
import asyncio
import os

from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter
from arclith.adapters.outbound.vault.tenant_adapter import VaultTenantResolver


async def main() -> None:
    resolver = VaultTenantResolver(
        "mongodb",
        addr=os.environ["VAULT_ADDR"],
        mount="kv",
        path_prefix="rekipe/tenants",
        cache=MemoryCacheAdapter(),
    )
    context = await resolver.resolve("client-a")
    coords = context.get("mongodb")
    assert coords is not None and coords.require("uri")
    print("Tenant résolu :", coords.require("db_name"))


asyncio.run(main())
PY
```

Le résultat attendu est `Tenant résolu : todo_client_a`. Contrairement au resolver de secrets
applicatifs, `VaultTenantResolver` lit tous les champs du chemin tenant, les place dans une tranche
`AdapterTenantCoords` et peut les mettre en cache. L'activation réelle du repository multitenant
requiert aussi `multitenant=true` et le pipeline JWT décrit dans la capability
[tenant](../../capabilities/tenant.md).

### Réinitialiser et diagnostiquer

```bash
# Supprime le container et toutes les données en mémoire du POC.
docker stop arclith-vault

# Retire le token jetable du terminal courant.
unset VAULT_TOKEN VAULT_ADDR
```

Erreurs fréquentes :

- `permission denied` : vérifier que `VAULT_TOKEN` correspond au lancement dev courant ;
- `no handler for route` : relancer `scripts/seed-vault.sh` pour activer le mount KV v2 ;
- secret applicatif non résolu : vérifier le champ `value`, le mapping et l'extra `arclith[vault]` ;
- tenant introuvable : vérifier le préfixe `rekipe/tenants` et l'identifiant `client-a` ;
- container redémarré : le stockage dev est en mémoire, il faut donc rejouer le seed.

Références : [serveur Vault en mode dev](https://developer.hashicorp.com/vault/docs/concepts/dev-server)
et [configuration d'un mount KV v2](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2/setup).

## Ajouter OpenTelemetry localement

LangSmith observe surtout les runs LLM et LangGraph. OpenTelemetry sert à tracer le service comme un
microservice classique: requêtes HTTP, spans, latences et erreurs techniques.

### Démarrer Jaeger

Pour ce POC, l'image Jaeger all-in-one regroupe le Collector OTLP, le stockage temporaire et l'UI.
Elle ne crée ni compte distant ni volume Docker : arrêter le container efface les traces du labo.

```bash
docker run --rm --name arclith-jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 5778:5778 \
  -p 9411:9411 \
  -d cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
```

Attendre que l'API de requête Jaeger réponde, puis ouvrir son UI :

```bash
for attempt in $(seq 1 30); do
  curl -fsS http://127.0.0.1:16686/api/services >/dev/null && break
  if [ "$attempt" -eq 30 ]; then
    docker logs arclith-jaeger
    exit 1
  fi
  sleep 1
done
```

```text
http://127.0.0.1:16686
```

Les ports utiles ici sont `4318` pour OTLP HTTP et `16686` pour l'UI. Le runtime Todo s'exécute sur
l'hôte et envoie donc ses traces à `http://127.0.0.1:4318`. Arclith ajoute automatiquement le chemin
OTLP `/v1/traces` pour le protocole `http/protobuf`.

### Configurer le projet Todo

Depuis la racine du projet généré, ajouter l'adapter avec les paramètres du catalogue courant :

```bash
uv add "arclith[opentelemetry]"
arclith-cli add-adapter \
  --capability observability \
  --adapter opentelemetry \
  --profile development \
  --param service_name=todo-list-service \
  --param endpoint=http://127.0.0.1:4318 \
  --param metrics=false \
  --yes
```

Le profil `development` active les traces à 100 %. `metrics=false` évite d'envoyer des métriques à
Jaeger, qui sert ici de backend de traces. Le CLI active `opentelemetry` dans
`config/adapters/adapters.yaml` et génère notamment :

```yaml
# config/adapters/outbound/opentelemetry.yaml
service:
  name: "todo-list-service"
export:
  protocol: "http/protobuf"
  endpoint: "http://127.0.0.1:4318"
signals:
  traces:
    enabled: true
  metrics:
    enabled: false
```

Pour identifier ce lancement dans les ressources OpenTelemetry, exporter la variable avant de
démarrer l'API :

```bash
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local
MODE=api uv run python main.py
```

### Produire et retrouver une trace

Dans un second terminal, appeler une route métier. `/health`, `/ready` et `/metrics` sont exclus de
l'instrumentation par défaut et ne conviennent donc pas à ce smoke :

```bash
curl -i -fsS "http://127.0.0.1:8120/v1/todos/?page=1&per_page=20"
```

Le runtime exporte par lot. Après quelques secondes, vérifier sans dépendre de l'UI que Jaeger a
indexé le service et au moins une trace :

```bash
curl -fsS http://127.0.0.1:16686/api/services | uv run python -m json.tool
curl -fsS \
  "http://127.0.0.1:16686/api/traces?service=todo-list-service&limit=20" \
  | uv run python -c 'import json, sys; print(len(json.load(sys.stdin)["data"]))'
```

La première commande doit contenir `todo-list-service`; la seconde doit afficher un entier supérieur
ou égal à `1`. Dans l'UI Jaeger, sélectionner ce service, cliquer sur **Find Traces**, puis ouvrir la
trace dont l'opération est `GET /v1/todos/`.

### Arrêter, relancer ou réinitialiser

```bash
# Arrêt propre ; --rm supprime ensuite le container et ses traces en mémoire.
docker stop arclith-jaeger

# Relance à neuf : réexécuter la commande docker run de cette section.
```

Erreurs fréquentes :

- `port is already allocated` : arrêter le processus ou le container qui utilise déjà `16686`,
  `4317` ou `4318`, puis relancer Jaeger ;
- `connection refused` sur `4318` : vérifier `docker ps --filter name=arclith-jaeger` et
  `docker logs arclith-jaeger` ;
- service absent dans Jaeger : appeler une route métier non exclue, attendre le prochain export par
  lot et vérifier `signals.traces.enabled`, le sampling et l'endpoint ;
- export `404` sur `/v1/metrics` : conserver `metrics=false` pour ce POC Jaeger, ou utiliser un
  OpenTelemetry Collector configuré avec un backend de métriques ;
- projet lui-même dans Docker : `127.0.0.1` désigne alors son propre container ; placer le service et
  Jaeger sur le même réseau Docker et utiliser le nom du service Jaeger à la place.

Le smoke Docker est volontairement manuel : la construction de la documentation ne suppose pas un
daemon Docker disponible en CI. La commande a été vérifiée avec l'image épinglée, l'export OTLP HTTP,
l'API Jaeger et une trace FastAPI portant le service `todo-list-service`.

## LangSmith ou OpenTelemetry ?

Les deux sont complémentaires:

| Besoin | Outil |
| --- | --- |
| comprendre les messages envoyés au modèle | LangSmith |
| voir pourquoi l'agent repose une question | LangSmith Studio |
| mesurer les appels HTTP et les erreurs techniques | OpenTelemetry |
| corréler plusieurs microservices | OpenTelemetry |

Pour ce tutoriel, LangSmith aide à apprendre l'agent. OpenTelemetry prépare la suite production.
Pour travailler sans internet, garder LangSmith désactivé et suivre
[Validation IA locale et hors ligne](../../learning/local-ai-validation.md).

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
