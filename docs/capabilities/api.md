# Capability API

Le CLI crée les fichiers et packages du [blueprint complet de cette
capability](../deep-dives/adapter-blueprints.md) uniquement lorsque `api/fastapi` est ajouté.
Il ajoute alors l'extra `arclith[fastapi]`. Les fichiers existants sont préservés lors d'une
relance.

Transport HTTP REST exposé via FastAPI.

## Objectif

L'API est un adapter inbound. Elle traduit HTTP vers les ports inbound ou les
use cases. Elle ne contient pas la logique métier et ne dépend pas d'un
repository concret.

## Adapter

| Adapter | Usage |
|---|---|
| `fastapi` | application FastAPI créée par `Arclith.fastapi()` |

## Commande

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes
```

## Configuration Générée

```yaml
# config/adapters/inbound/fastapi.yaml
host: 0.0.0.0
port: 8000
reload: true
```

## Créer L'application

```python
from arclith import Arclith

from todo_service.adapters.inbound.fastapi.register import register_routes
from todo_service.infrastructure.use_cases_generated import build_use_cases

arclith = Arclith("config")
app = arclith.fastapi()
register_routes(app, build_use_cases(arclith))
```

`Arclith.fastapi()` configure le titre, la version et la description depuis la
configuration applicative. Il ajoute aussi les middlewares HTTP et
l'observabilité activés.

## Exposer Une Route

```bash
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
```

La route générée valide et convertit le payload HTTP, appelle le port inbound,
puis convertit le résultat en DTO de réponse. La chaîne de routers
`application -> v1 -> feature -> opération` n'inclut chaque niveau qu'une fois.
Le transport ne publie pas directement l'entité du domaine.

## Projeter Une Feature CRUD

Lorsqu'une feature possède un manifeste de blueprint CRUD, exposer son contrat
REST complet sans répéter cinq commandes :

```bash
arclith-cli add-entity Todo --profile crud
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

`expose-feature` projette ensemble `POST /v1/todos`, les lectures collection et
item, `PATCH /v1/todos/{uuid}` et `DELETE /v1/todos/{uuid}`. Le chemin `uuid`
reste un paramètre FastAPI typé, puis le mapper reconstruit la Command ou Query
applicative. Les erreurs `NotFound` et `VersionConflict` générées par le
blueprint deviennent `404` et `409` au bord HTTP.

La projection exige un adapter déjà installé, prévalide toutes les collisions
et compose les cinq ports depuis un seul container applicatif. Elle ne choisit
pas de repository et ne modifie pas les règles métier. Pour un use case isolé,
continuer à utiliser `expose-usecase`.

## Auth

```python
from fastapi import Depends

require_auth = arclith.auth_dependency()
secure_router = APIRouter(
    prefix="/v1/todos",
    tags=["todos"],
    dependencies=[Depends(require_auth)],
)
```

Quand Keycloak est configuré, Swagger UI reçoit le flow OAuth2 PKCE et les routes
protégées utilisent la même validation JWT.

## Probes Et Observabilité

Si `probe/server` est actif, lancer l'API avec les probes :

```python
arclith.run_with_probes(lambda: arclith.run_api("main:app"), transports=["api"])
```

Pour garder l'import FastAPI optionnel dans un projet généré tout en permettant l'auto-reload,
utiliser une factory importable :

```python
arclith.run_api("main:build_api", factory=True)
```

Une instance FastAPI directe reste acceptée, mais Uvicorn désactive alors le reload.

Le port API sert le métier. Le port probe sert `/health`, `/ready`, `/info` et
`/metrics`.

## Règles

- Une route appelle un port inbound ou un use case.
- Une route ne crée pas de repository concret.
- Les erreurs métier doivent être converties en erreurs HTTP explicites.
- Les middlewares HTTP transverses sont dans la capability [http](http.md).
- Les contrats HTTP publics doivent être testés avec `TestClient` ou `httpx`.
- Une projection de feature doit rester explicite et consommer son manifeste
  canonique ; ne pas inférer un CRUD depuis l'adapter.

## Validation

```bash
MODE=api uv run python main.py
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:8000/docs
```

## Suite

Lire [http](http.md), [auth](auth.md), puis [Deep Dive API](../deep-dives/api.md).
