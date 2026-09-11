# 5. Exposer un MCP FastMCP

Objectif : ajouter FastMCP seulement lorsque le service doit exposer MCP, puis
publier le même port applicatif que l'API.

```bash
arclith-cli add-adapter \
  --capability mcp \
  --adapter fastmcp \
  --param host=127.0.0.1 \
  --param port=8121 \
  --yes

arclith-cli expose-usecase CreateTodo \
  --via fastmcp \
  --feature todos \
  --name create_todo
```

Ces commandes ajoutent `arclith[mcp]`; elles ne créent aucune route FastAPI.

## Structure attendue

```text
adapters/inbound/fastmcp/
├── README.md
├── register.py
├── bindings_generated.py
├── dependencies.py
├── errors.py
├── contracts/create_todo.py
├── middleware/
└── features/
    └── todos/
        ├── README.md
        ├── register.py
        ├── schemas.py
        ├── mappers.py
        ├── presenters.py
        ├── tools/create_todo.py
        ├── resources/
        └── prompts/
```

`tools`, `resources` et `prompts` sont trois primitives distinctes. Une action
de use case est exposée comme tool ; le CLI ne crée pas de resource ni de prompt
fictif. Chaque primitive appelle un port inbound et ne connaît aucun repository
concret.

Sous-étapes :

1. [Tool et contrat MCP](05-mcp-tools.md)
2. [Entrypoint et tests](05-mcp-entrypoint-tests.md)
3. [Connexion depuis LM Studio](05-mcp-lm-studio.md)
