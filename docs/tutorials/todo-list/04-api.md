# 4. Exposer une API FastAPI

Objectif : installer uniquement FastAPI puis exposer un use case par une route
typée, sans dupliquer le préfixe de version ni créer une feature implicite.

```bash
arclith-cli add-adapter \
  --capability api \
  --adapter fastapi \
  --param host=127.0.0.1 \
  --param port=8120 \
  --param reload=true \
  --yes

arclith-cli expose-usecase CreateTodo \
  --via fastapi \
  --feature todos \
  --path /v1/todos \
  --method POST \
  --status-code 201
```

La première commande ajoute `arclith[fastapi]`, la configuration et le socle
du transport. La seconde crée uniquement la feature `todos` et le binding du
use case existant.

## Structure attendue

```text
adapters/inbound/fastapi/
├── README.md
├── register.py
├── bindings_generated.py
├── dependencies.py
├── errors.py
├── contracts/
├── middleware/
└── routers/
    └── v1/
        ├── router.py
        └── todos/
            ├── README.md
            ├── router.py
            ├── schemas.py
            ├── mappers.py
            ├── presenters.py
            ├── openapi.py
            └── routes/create_todo.py
```

La chaîne d'inclusion est unique :

```text
main.build_api
  -> fastapi/register.py
  -> routers/v1/router.py          # propriétaire du préfixe /v1
  -> routers/v1/todos/router.py
  -> routes/create_todo.py         # chemin local /todos
```

Les DTO de transport restent sous FastAPI. La route mappe la requête vers le
`CreateTodoCommand`, appelle `CreateTodoPort`, puis présente un
`CreateTodoResponse`. Elle ne construit pas de repository et ne contient pas de
règle métier.

Sous-étapes :

1. [Contrats et schémas](04-api-config-schemas.md)
2. [Binding HTTP](04-api-handlers.md)
3. [Router et composition](04-api-router-main.md)
4. [Tests de l'API](04-api-tests.md)
