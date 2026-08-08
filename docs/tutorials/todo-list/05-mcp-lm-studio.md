# 5.3 Tester le MCP dans LM Studio

Intention: vérifier qu'un client MCP piloté par un modèle peut découvrir et appeler les tools du
service.

Garder le serveur MCP Arclith lancé:

```bash
MODE=mcp_http uv run python main.py
```

Dans LM Studio:

1. Ouvrir le panneau de droite.
2. Aller dans l'onglet `Program`.
3. Cliquer sur `Install`, puis `Edit mcp.json`.
4. Ajouter le serveur MCP du tutoriel.

Si le fichier est vide, utiliser:

```json
{
  "mcpServers": {
    "todo-list-service": {
      "url": "http://127.0.0.1:8121/mcp"
    }
  }
}
```

Tester ensuite dans un chat LM Studio:

```text
Utilise les tools disponibles pour créer une todo:
titre Tester LM Studio MCP, description Appel MCP depuis LM Studio,
échéance 2026-09-01, statut todo.
```

Le test est réussi si LM Studio voit les tools `create_todo_item` et `list_todo_items`, appelle le
serveur `http://127.0.0.1:8121/mcp`, et que les logs du service Arclith montrent l'appel entrant.

![Flux LM Studio vers MCP Arclith](assets/05-lmstudio-mcp.svg)

Étape suivante: [ajouter un agent](06-agent.md).
