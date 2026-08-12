# Quickstarts

Ces pages servent à vérifier les flux les plus fréquents en quelques minutes.

## Choisir

| Besoin | Page |
|---|---|
| Démarrer un service HTTP | [API](api.md) |
| Exposer des tools MCP | [MCP](mcp.md) |
| Ajouter un worker RabbitMQ | [Bus](bus.md) |
| Préparer un agent LangGraph | [Agent](agent.md) |

## Projet De Départ

Si tu n'as pas encore de projet Arclith :

```bash
uvx --from arclith-cli arclith-cli init my-service --dir .
cd my-service
uv sync
```

Les quickstarts partent ensuite de ce dossier.

## Règle

Un quickstart valide seulement le bootstrap.

Pour écrire du métier réel, suivre le [parcours Todo](../tutorials/todo-list/index.md).

## Suite

Commencer par [API](api.md).
