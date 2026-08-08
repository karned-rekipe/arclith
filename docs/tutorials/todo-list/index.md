# Tutoriel Todo List

Ce tutoriel part de zéro et construit une todo list Arclith étape par étape. L'objectif est de
montrer comment garder le métier simple pendant que l'on branche FastAPI, MCP, LangGraph,
LM Studio, LangSmith, MongoDB et OpenTelemetry autour.

![Flux Arclith Todo](assets/architecture-flow.svg)

## Projet téléchargeable

Le dépôt complet du tutoriel est disponible ici:
<https://github.com/karned-rekipe/arclith-POC-todo>.

```bash
git clone https://github.com/karned-rekipe/arclith-POC-todo.git
cd arclith-POC-todo
uv sync
uv run python -m pytest
```

Le dépôt permet de comparer votre progression avec un projet complet. Les pages ci-dessous restent
la source principale: elles expliquent les générations CLI, puis les fichiers à créer ou modifier.

## Méthodologie Arclith

Arclith pousse une démarche hexagonale simple: on commence par le métier, puis on branche les outils
autour. Le coeur se construit dans cet ordre:

1. créer les entités qui portent les données et règles métier;
2. définir les ports inbound, c'est-à-dire les intentions que l'application expose;
3. écrire les use cases qui implémentent ces ports et orchestrent le métier;
4. brancher les adapters inbound comme FastAPI, FastMCP ou LangGraph;
5. choisir les adapters outbound comme `memory` ou MongoDB pour la persistance.

Cette séparation rend l'API, le MCP, l'agent et la base de données remplaçables sans déplacer le
métier. Les use cases se testent sans serveur web, sans serveur MCP, sans LangGraph et sans MongoDB.

Le fil conducteur contient:

- une entité `Todo`;
- deux ports inbound `CreateTodoPort` et `ListTodosPort`;
- deux use cases applicatifs pour enregistrer et lister les todos;
- une API FastAPI;
- un serveur MCP FastMCP;
- un agent LangGraph capable de créer une todo, lister les todos et annuler une création en cours;
- un adapter MongoDB pour partager les données entre plusieurs processus.

## Modèle cible

Une todo contient:

| Champ | Type | Règle |
| --- | --- | --- |
| `title` | `str` | obligatoire, non vide |
| `description` | `str` | optionnel côté API et agent, stocké comme chaîne |
| `due_date` | `date` | obligatoire |
| `completed_at` | `datetime | None` | renseigné seulement si le statut est `done` |
| `status` | `todo | wip | done` | `todo` par défaut |

## Architecture

```text
Client HTTP / Client MCP / LangGraph
  -> adapter inbound
  -> CreateTodoPort / ListTodosPort
  -> use case applicatif
  -> Repository[Todo]
  -> memory en test, MongoDB en runtime multi-processus
```

Les adapters inbound ne parlent jamais directement au repository. Ils appellent les ports inbound.
L'agent transforme une conversation en décision ou en commande structurée, puis appelle
`CreateTodoPort` ou `ListTodosPort`.

## Étapes

0. [Préparer LM Studio](00-lm-studio.md), utile pour l'étape agent
1. [Initialiser le projet](01-init-project.md)
2. [Créer l'entité Todo](02-create-entity.md)
3. [Créer les use cases](03-create-usecase.md)
4. [Exposer une API FastAPI](04-api.md)
5. [Exposer un MCP FastMCP](05-mcp.md)
6. [Ajouter un agent LangGraph](06-agent.md)
7. [Annexes locales: MongoDB, Compass et OpenTelemetry](07-local-services.md)

Chaque page montre le mode interactif de la CLI, puis les fichiers à créer ou modifier. La voie
rapide non interactive est donnée en fin de page pour les scripts et les reprises.

## Prérequis

- Python 3.13;
- `uv`;
- `git`;
- Docker pour MongoDB et OpenTelemetry;
- LM Studio pour l'agent et le test MCP depuis LM Studio;
- une clé LangSmith si vous voulez tracer l'agent dans LangSmith.

Installer la CLI publiée:

```bash
uv tool install --force "arclith-cli>=0.12.0"
arclith-cli version
```

Le tutoriel utilise ensuite un projet local `todo-list-service`.
