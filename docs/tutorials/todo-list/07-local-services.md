# Annexes locales

Objectif: donner les commandes minimales pour faire tourner les briques locales utilisées en fin de
tutoriel: MongoDB, lecture de la base, secrets locaux et OpenTelemetry.

Cette page répond à la phrase: "Configurer l'URI MongoDB via le resolver de secrets local, puis
relancer API, MCP et LangGraph."

![Services locaux autour du Todo service](assets/07-local-services.svg)

## Pourquoi MongoDB à cette étape ?

Au début du tutoriel, le repository `memory` suffit. Il garde les todos en mémoire dans le processus
Python courant.

Cela devient limité dès qu'on lance plusieurs processus:

- l'API FastAPI tourne dans un processus;
- le serveur MCP tourne dans un autre processus;
- LangGraph tourne encore dans un autre processus.

Chaque processus a alors sa propre mémoire. MongoDB sert de stockage partagé pour que les trois
canaux lisent et écrivent les mêmes todos.

## Lancer MongoDB avec Docker

Commande minimale:

```bash
docker run --name arclith-mongo \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=arclith \
  -e MONGO_INITDB_ROOT_PASSWORD=arclith \
  -v arclith-mongo-data:/data/db \
  -d mongo:8
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
db_name (todo-list-service): todo_list_service
multitenant [y/n] (n): n
Activer mongodb maintenant ? [y/n] (y): y
```

La configuration non secrète doit ressembler à ceci:

```yaml
# config/adapters/adapters.yaml
repository: mongodb
```

```yaml
# config/adapters/outbound/mongodb.yaml
db_name: todo_list_service
multitenant: false
collection_name: todo
```

`collection_name` est optionnel. Si la valeur est absente, Arclith dérive le nom depuis la classe
entité: `Todo` devient `todo`.

## Déclarer l'URI comme secret local

L'URI contient le mot de passe MongoDB. Elle ne doit donc pas être écrite dans
`config/adapters/outbound/mongodb.yaml`.

Créer ou compléter `config/secrets.yaml`:

```yaml
resolver: yaml
mappings:
  adapters.mongodb.uri: adapters.mongodb.uri
```

Créer ensuite `secrets.yaml` à la racine du projet:

```yaml
adapters:
  mongodb:
    uri: "mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin"
```

Ajouter ce fichier local à `.gitignore`:

```text
secrets.yaml
```

Lire la configuration comme ceci:

- `config/secrets.yaml` est commit-able: il dit quel champ doit être rempli;
- `secrets.yaml` n'est pas commit-able: il contient la vraie valeur locale;
- au chargement, Arclith injecte `adapters.mongodb.uri` avant de construire le repository.

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

MongoDB Compass est l'interface graphique officielle pour inspecter une base locale.

Connexion:

```text
mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin
```

À vérifier:

- base: `todo_list_service`;
- collection: `todo`, sauf si vous avez choisi un autre `collection_name`;
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

Si vous n'avez pas fixé `collection_name: todo`, regarder d'abord le résultat de
`show collections`.

## Ajouter OpenTelemetry localement

LangSmith observe surtout les runs LLM et LangGraph. OpenTelemetry sert à tracer le service comme un
microservice classique: requêtes HTTP, spans, latences et erreurs techniques.

Pour un labo local, Jaeger all-in-one suffit:

```bash
docker run --rm --name arclith-jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 5778:5778 \
  -p 9411:9411 \
  -d cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
```

Ouvrir ensuite:

```text
http://127.0.0.1:16686
```

Référence officielle Jaeger: <https://www.jaegertracing.io/docs/2.20/getting-started/>.

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

Étape précédente: [ajouter un agent](06-agent.md).
