# Capability Repository

Persistance des entités métier derrière un port repository.

## Objectif

Un repository est un adapter outbound. Les use cases dépendent du port
`Repository[T]`; le choix MongoDB, MariaDB, DuckDB ou mémoire reste dans la
configuration et l'assemblage applicatif.

## Choisir L'adapter

| Adapter | Usage |
|---|---|
| `memory` | tests unitaires, développement, un seul processus |
| `mongodb` | standard document, API/MCP/agent avec état partagé |
| `duckdb` | fichier local, démo, analytique embarquée |
| `mariadb` | SQL serveur, intégration SI existant |

## Installer

```bash
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability repository --adapter mongodb --yes
```

Pour MongoDB ou MariaDB, ajouter aussi le resolver de secrets adapté.

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter chain \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/my-service/mongodb \
  --yes
```

## Activer

```yaml
# config/adapters/adapters.yaml
repository: mongodb
```

## MongoDB

```yaml
# config/adapters/outbound/mongodb.yaml
uri: null
db_name: my_service
collection_name: null
multitenant: false
```

`uri: null` signifie que l'URI doit venir de `config/secrets.yaml`, de
l'environnement ou de Vault.

## MariaDB

```yaml
# config/adapters/outbound/mariadb.yaml
url: null
host: 127.0.0.1
port: 3306
database: my_service
user: app
password: null
driver: asyncmy
table_prefix: ""
multitenant: false
```

Mapper `adapters.mariadb.url` ou `adapters.mariadb.password` via secrets.

## DuckDB

```yaml
# config/adapters/outbound/duckdb.yaml
multitenant: false
path: data/
```

DuckDB est utile pour une démo locale ou un traitement analytique léger. Ne
l'utiliser en production que si le modèle de fichier local est explicitement
voulu.

## Utiliser Dans Un Service

```python
from arclith import Arclith
from my_service.domain.models.todo import Todo

app = Arclith("config")
repository = app.repository(Todo)
```

Dans un projet métier, centraliser cet assemblage dans un container
d'application pour partager le même repository entre API, MCP et agent.

## Règles

- Un adapter inbound ne doit jamais instancier un repository concret.
- Les use cases parlent au port `Repository[T]`.
- `memory` ne partage pas l'état entre processus API, MCP et agent.
- Les URI et mots de passe passent par la capability [secrets](secrets.md).
- La configuration choisit l'adapter actif; le code métier reste stable.

## Validation

```bash
uv run pytest
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
```

## Suite

Lire [secrets](secrets.md), puis [cache](cache.md) si plusieurs processus doivent
partager l'état technique.
