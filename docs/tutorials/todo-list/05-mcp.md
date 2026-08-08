# 5. Exposer un MCP

Objectif: générer la configuration FastMCP avec la CLI, puis exposer les mêmes opérations métier via
des tools MCP.

![Capture interactive FastMCP](assets/05-mcp.svg)

## Générer l'adapter

Depuis la racine du projet:

```bash
arclith-cli add-adapter --capability mcp
```

Répondre aux prompts:

```text
① Type d'adapter
   1  fastmcp

  Votre choix (numéro ou nom): 1

③ Paramètres fastmcp
  Host FastMCP (127.0.0.1): 127.0.0.1
  Port FastMCP (8001): 8121

  Confirmer la génération ? [y/n] (y): y
```

La CLI crée:

```text
config/adapters/inbound/fastmcp.yaml
```

## Sous-étapes

1. [Écrire les tools MCP](05-mcp-tools.md)
2. [Brancher le MCP et tester en mémoire](05-mcp-entrypoint-tests.md)
3. [Tester dans LM Studio](05-mcp-lm-studio.md)

## Rôle des fichiers MCP

| Fichier | Rôle |
| --- | --- |
| `config/adapters/inbound/fastmcp.yaml` | Configure le serveur MCP HTTP. |
| `adapters/inbound/fastmcp/tools/todo_tools.py` | Déclare les tools `create_todo_item` et `list_todo_items`, leurs paramètres typés et leur payload de retour. |
| `adapters/inbound/fastmcp/tools/__init__.py` | Exporte `TodoMCP` pour garder un import stable côté registration. |
| `adapters/inbound/fastmcp/register.py` | Construit les use cases via le container et installe les tools sur l'instance FastMCP. |
| `main.py` | Conserve un seul point d'entrée pour API, MCP HTTP ou les deux transports. |

Un tool MCP adapte un appel tool vers un port inbound, comme l'API adapte une requête HTTP vers le
même port.

Étape suivante: [écrire les tools MCP](05-mcp-tools.md).
