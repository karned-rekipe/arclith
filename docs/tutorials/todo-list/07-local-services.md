# Annexes locales

Cette annexe branche les providers locaux sans créer de wrapper par entité.
Chaque provider doit d'abord être choisi avec `add-adapter`; la CLI ajoute son
extra, sa configuration et son blueprint fermé.

## MongoDB

MongoDB est utile lorsque FastAPI, FastMCP ou un worker tournent dans des
processus distincts. Démarrer une instance locale :

```bash
docker run --rm -d \
  --name arclith-mongo \
  -p 127.0.0.1:27017:27017 \
  mongo:8.0
```

Choisir MongoDB dans le projet :

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mongodb \
  --db-name todo_list_service \
  --param collection_name=todos \
  --yes
uv sync
```

La commande produit uniquement :

```text
config/adapters/adapters.yaml              # repository: mongodb
config/adapters/outbound/mongodb.yaml
config/secrets.yaml                         # mapping vers MONGODB_URI
src/todo_list_service/adapters/outbound/mongodb/
.arclith/blueprints/repository-mongodb.yaml
```

Elle ne crée ni adapter `memory`, ni `MongoDBTodoRepository`, ni container par
entité. `Arclith.repository(Todo)` instancie l'implémentation générique
`MongoDBRepository[Todo]`; les types usuels, dont les dates et les UUID, sont
déjà sérialisés par le framework.

Configurer le secret hors Git puis lancer le transport choisi :

```bash
export MONGODB_URI=mongodb://127.0.0.1:27017
MODE=api uv run python main.py
```

Contrôler les documents :

```bash
docker exec arclith-mongo mongosh --quiet todo_list_service \
  --eval 'printjson(db.todos.find().toArray())'
```

Arrêter le service de test :

```bash
docker stop arclith-mongo
```

Un fichier projet sous `adapters/outbound/mongodb/repositories/` n'est créé que
pour un port outbound métier réellement absent de `Repository[T]`, par exemple
une recherche agrégée spécifique. Les modèles provider, mappers, indexes et
migrations vont dans les rôles homonymes déjà documentés par le blueprint ; il
est interdit d'inventer un second arbre.

## Autres services locaux

- [Authentification et Keycloak](../../auth.md)
- [Observabilité OpenTelemetry et LangSmith](../../capabilities/observability.md)
- [Exploitation de l'observabilité](../../production/observability.md)
- [Runtime Docker](../../runtime-docker.md)

Appliquer le même principe : ajouter seulement la capability utilisée, garder
les secrets hors Git, lire le README généré de l'adapter et tester le provider
réel avant de livrer.

## Ajouter Vault localement

Ajouter d'abord `secrets/vault` avec `add-adapter`, puis suivre le
[guide des secrets](../../capabilities/secrets.md). Aucun resolver Vault ne doit
être créé si cette capability n'est pas sélectionnée.

## Ajouter Keycloak localement

Ajouter explicitement les capabilities d'authentification nécessaires, puis
suivre le [guide d'authentification](../../auth.md). Keycloak n'appartient ni au
domaine ni à un use case.

## Ajouter OpenTelemetry localement

Ajouter `observability/opentelemetry` avec `add-adapter`, puis suivre le
[guide d'observabilité](../../capabilities/observability.md). Les exporters et
instrumentations restent dans les rôles déclarés par le blueprint.
