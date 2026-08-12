# Capability API

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
from fastapi import APIRouter

arclith = Arclith("config")
app = arclith.fastapi()

router = APIRouter(prefix="/v1/todos", tags=["todos"])
app.include_router(router)
```

`Arclith.fastapi()` configure le titre, la version et la description depuis la
configuration applicative. Il ajoute aussi les middlewares HTTP et
l'observabilité activés.

## Écrire Une Route

```python
from fastapi import status

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_todo(payload: CreateTodoRequest) -> TodoResponse:
    command = payload.to_command()
    result = await create_todo_use_case.execute(command)
    return TodoResponse.from_entity(result)
```

La route valide et convertit le payload HTTP, appelle un use case, puis convertit
le résultat en réponse HTTP.

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

Le port API sert le métier. Le port probe sert `/health`, `/ready`, `/info` et
`/metrics`.

## Règles

- Une route appelle un port inbound ou un use case.
- Une route ne crée pas de repository concret.
- Les erreurs métier doivent être converties en erreurs HTTP explicites.
- Les middlewares HTTP transverses sont dans la capability [http](http.md).
- Les contrats HTTP publics doivent être testés avec `TestClient` ou `httpx`.

## Validation

```bash
MODE=api uv run python main.py
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:8000/docs
```

## Suite

Lire [http](http.md), [auth](auth.md), puis [Deep Dive API](../deep-dives/api.md).
