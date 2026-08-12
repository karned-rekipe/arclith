# Quickstarts Essentiels

Cette page regroupe les démarrages rapides les plus utilisés.

## Objectif

Exécuter les quatre modes fréquents sans entrer encore dans tous les détails:
API, MCP, bus et agent.

## Ordre Recommandé

1. [Quickstart API](../quickstarts/api.md)
2. [Quickstart MCP](../quickstarts/mcp.md)
3. [Quickstart bus](../quickstarts/bus.md)
4. [Quickstart agent](../quickstarts/agent.md)

Chaque quickstart est volontairement court. Les explications longues sont dans
les pages capabilities et deep dives.

## Validations

| Mode | Validation minimale |
|---|---|
| API | `curl -fsS http://127.0.0.1:8000/health` |
| MCP | tool MCP visible depuis le client choisi |
| Bus | message publié puis consommé |
| Agent | graphe lancé et premier échange exécuté |

## Quand S'arrêter

Si un quickstart échoue, rester sur ce mode avant de passer au suivant. La
formation doit produire un service qui tourne, pas seulement des fichiers.

## Liens D'approfondissement

- [Capability API](../capabilities/api.md)
- [Capability MCP](../capabilities/mcp.md)
- [Capability Command Bus](../capabilities/command-bus.md)
- [Capability Agent](../capabilities/agent.md)

## Média

!!! note "Média à produire"
    Capture attendue : un terminal par quickstart avec la commande de validation.
    Vidéo attendue : enchaînement API, MCP, bus, agent sans approfondissement.

## Suite

Suivre le [projet Todo](../tutorials/todo-list/index.md).
