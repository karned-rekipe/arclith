# Tutoriel Todo List

Ce tutoriel part de zéro et construit une todo list Arclith étape par étape.

Le fil conducteur est volontairement simple:

- une entité `Todo`;
- un port inbound `CreateTodoPort`;
- un use case `CreateTodoUseCase` pour enregistrer une todo;
- une API FastAPI;
- un serveur MCP FastMCP;
- un agent LangGraph qui collecte les champs manquants avant d'appeler le même use case.

Le chemin principal utilise `repository: memory`. À la fin, on ajoute MongoDB pour partager les
données entre l'API, le MCP et l'agent quand ils tournent dans des processus différents.

## Modèle cible

Une todo contient:

| Champ | Type | Règle |
| --- | --- | --- |
| `title` | `str` | obligatoire, non vide |
| `description` | `str` | optionnel côté API, stocké comme chaîne |
| `due_date` | `date` | obligatoire |
| `completed_at` | `datetime | None` | renseigné seulement si le statut est `done` |
| `status` | `todo | wip | done` | `todo` par défaut |

## Architecture

```text
Client HTTP / Client MCP / LangGraph
  -> adapter inbound
  -> CreateTodoPort
  -> CreateTodoUseCase
  -> Repository[Todo]
  -> memory, puis MongoDB
```

L'agent ne persiste jamais directement. Il transforme une conversation en commande structurée puis
appelle `CreateTodoPort`, exactement comme l'API et le MCP.

## Étapes

1. [Initialiser le projet](01-init-project.md)
2. [Créer l'entité Todo](02-create-entity.md)
3. [Créer le use case d'enregistrement](03-create-usecase.md)
4. [Exposer une API FastAPI](04-api.md)
5. [Exposer un MCP FastMCP](05-mcp.md)
6. [Ajouter un agent LangGraph](06-agent.md)

Chaque page montre le mode interactif de la CLI. La voie rapide non interactive est donnée en fin de
page pour les scripts et les reprises.

## Prérequis

- Python 3.13;
- `uv`;
- `git`;
- LM Studio seulement pour la dernière étape agent;
- une clé LangSmith seulement si vous voulez tracer l'agent dans LangSmith.

Installer la CLI depuis le repository pour utiliser les dernières commandes:

```bash
uv tool install --force "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
arclith-cli version
```

Le tutoriel utilise ensuite un projet local `todo-list-service`.
