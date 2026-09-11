# 5.1 Tool et contrat MCP

Le tool n'est pas créé dans un dossier global `fastmcp/tools`. Il appartient à
sa feature :

```text
src/todo_list_service/adapters/inbound/fastmcp/
├── contracts/create_todo.py
└── features/todos/tools/create_todo.py
```

`contracts/create_todo.py` définit le DTO d'entrée, le mapping vers
`CreateTodoCommand`, le DTO de sortie et le presenter. Le tool reçoit
`CreateTodoPort` par injection et exécute uniquement cette séquence :

```text
payload MCP
  -> CreateTodoRequest
  -> CreateTodoCommand
  -> CreateTodoPort.execute
  -> CreateTodoResponse
```

Le nom public est explicite :

```bash
arclith-cli expose-usecase CreateTodo \
  --via fastmcp \
  --feature todos \
  --name create_todo
```

Une relance préserve les fichiers développeur et met seulement à jour les
agrégateurs `*_generated.py` et le manifeste `.arclith/bindings/fastmcp.json`.
Ne pas ajouter une seconde fonction d'enregistrement ou un dossier `common/` ;
les points d'extension permis sont documentés dans les README de l'adapter.

Étape suivante : [entrypoint et tests](05-mcp-entrypoint-tests.md).
