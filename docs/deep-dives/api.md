# Deep Dive API

Cette page explique comment penser une API FastAPI dans Arclith.

## Position

L'API est un adapter inbound. Elle reçoit HTTP, valide le contrat externe, puis
appelle un port inbound ou un use case.

```text
HTTP request
  -> FastAPI route
  -> schéma d'entrée
  -> use case
  -> schéma de sortie
  -> HTTP response
```

La route ne contient pas la règle métier. Elle traduit un protocole.

## Création De L'application

```python
from arclith import Arclith

arclith = Arclith("config")
app = arclith.fastapi()
```

`Arclith.fastapi()` applique les conventions transverses disponibles:
configuration de l'application, middlewares HTTP, instrumentation OpenTelemetry
si activée, et patch Swagger OAuth2 quand Keycloak est configuré.

## Route Propre

Une route propre fait trois choses:

1. valider l'entrée HTTP;
2. appeler le use case;
3. convertir le résultat en réponse HTTP.

```python
@router.post("/", status_code=201)
async def create_todo(payload: CreateTodoRequest) -> TodoResponse:
    command = payload.to_command()
    todo = await create_todo_use_case.execute(command)
    return TodoResponse.from_entity(todo)
```

Le use case ne doit pas recevoir `Request`, `Response`, `Depends`, `HTTPException`
ou un repository concret.

## Auth Et Licence

```python
from fastapi import APIRouter, Depends

require_auth = arclith.auth_dependency()

router = APIRouter(
    prefix="/v1/todos",
    dependencies=[Depends(require_auth)],
)
```

Le pipeline JWT peut aussi vérifier la capability `license` si elle est
configurée. Une erreur d'authentification donne `401`; une licence manquante
donne `403`.

## Multitenant

En mode multitenant, brancher la dépendance de résolution tenant sur les routes
qui accèdent à un repository multitenant. Le tenant vient d'un claim JWT signé,
puis les coordonnées techniques sont résolues via les resolvers configurés.

Le handler API ne doit pas accepter une URI tenant depuis le client.

## HTTP Transverse

Les concerns HTTP transverses restent dans la capability [HTTP](../capabilities/http.md):

| Concern | Rôle |
|---|---|
| idempotence | sécuriser les retries de commandes |
| ETag | gérer les lectures conditionnelles |
| Cache-Control | expliciter le comportement de cache client |
| timing | mesurer la latence des routes |

## Observabilité

Quand les probes sont activées, séparer le port métier du port d'observation.

```python
arclith.run_with_probes(lambda: arclith.run_api("main:app"), transports=["api"])
```

Le port API sert `/v1/...`. Le port probe sert `/health`, `/ready`, `/info` et
`/metrics`.

## Erreurs Fréquentes

| Erreur | Correction |
|---|---|
| route qui instancie un repository | injecter un use case déjà câblé |
| `HTTPException` dans le domaine | lever une erreur métier puis convertir en API |
| secret dans le schéma de réponse | filtrer dans `TodoResponse.from_entity` |
| Swagger auth ambigu | vérifier la config Keycloak et `client_id` |
| healthcheck sur le port API | utiliser le port probe si `run_with_probes` est actif |

## Validation

```bash
MODE=api uv run python main.py
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:8000/docs
uv run pytest
```

Un test API minimal doit vérifier le statut, le JSON de sortie et l'appel réel
du use case avec une dépendance de test.

## Pages Liées

- [Capability API](../capabilities/api.md)
- [Capability Auth](../capabilities/auth.md)
- [Capability HTTP](../capabilities/http.md)
- [Conventions HTTP](../http-conventions.md)
- [Tutoriel Todo API](../tutorials/todo-list/04-api.md)

## Média

!!! note "Média à produire"
    Capture : Swagger UI avec auth activée.
    Vidéo : route FastAPI qui appelle un use case.
