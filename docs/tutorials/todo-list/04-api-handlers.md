# 4.2 Binding HTTP

Arclith n'utilise pas un dossier libre `handlers/`. Chaque opération HTTP est
placée dans la feature et dans le rôle fermé `routes/` :

```text
src/todo_list_service/adapters/inbound/fastapi/
├── contracts/create_todo.py
└── routers/v1/todos/routes/create_todo.py
```

Le fichier d'opération est généré par :

```bash
arclith-cli expose-usecase CreateTodo \
  --via fastapi \
  --feature todos \
  --path /v1/todos \
  --method POST \
  --status-code 201
```

Son unique responsabilité est la traduction de protocole :

```text
CreateTodoRequest
  -> to_application
  -> CreateTodoPort.execute
  -> present_result
  -> CreateTodoResponse
```

Le port est injecté au moment de l'enregistrement. Le binding ne doit importer
ni `MongoDBRepository`, ni `InMemoryRepository`, ni le composition root concret.
Les validations métier appartiennent à `domain` ; les décisions d'orchestration
appartiennent à `application`.

Le module est développeur-propriétaire après sa création. Le CLI régénère
uniquement `bindings_generated.py`, jamais les personnalisations de l'opération.

Étape suivante : [router et composition](04-api-router-main.md).
