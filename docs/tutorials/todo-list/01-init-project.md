# 1. Initialiser le projet

Objectif : créer un projet Arclith minimal, installable et guidé, sans choisir
à la place du développeur ses transports ou sa persistance.

## Prérequis

```bash
uv tool install arclith-cli
arclith-cli version
```

Depuis le dossier parent :

```bash
arclith-cli init todo-list-service
cd todo-list-service
uv sync
uv run pytest
```

`init` ne crée ni entité, ni feature, ni FastAPI, ni FastMCP, ni RabbitMQ, ni
MongoDB, ni Dockerfile. La configuration sélectionne `memory` comme repository
fonctionnel par défaut, mais aucun dossier d'adapter n'est scaffoldé tant que
`add-adapter` n'est pas appelé.

## Arborescence canonique

```text
todo-list-service/
├── AGENTS.md
├── ARCHITECTURE.md
├── README.md
├── main.py
├── pyproject.toml
├── config/
│   ├── app.yaml
│   ├── soft_delete.yaml
│   └── adapters/
│       ├── adapters.yaml
│       ├── inbound/
│       ├── outbound/
│       └── bidirectional/
├── src/
│   └── todo_list_service/
│       ├── domain/{models,events,value_objects,ports}/
│       ├── application/{use_cases,services,workflows,intent_interpreters}/
│       ├── adapters/{inbound,outbound,bidirectional}/
│       └── infrastructure/{containers,bootstrap}/
└── tests/
```

Le niveau `src/todo_list_service` est intentionnel : `src/` isole le code du
checkout et `todo_list_service` est le namespace Python distribué. Des dossiers
globaux `domain/`, `application/` ou `adapters/` directement sous `src/`
créeraient des packages génériques susceptibles d'entrer en collision.

## Contrat obligatoire pour les agents

Le projet contient deux fichiers de gouvernance :

- `AGENTS.md` impose la lecture du contrat et interdit les racines parallèles,
  `utils.py`, `helpers.py` et les features déduites d'une entité ;
- `ARCHITECTURE.md` décrit chaque couche, les seuls points d'extension et les
  chaînes d'enregistrement des transports.

Chaque `add-adapter` ajoute ensuite un README par rôle et un manifeste fermé
`.arclith/blueprints/<capability>-<adapter>.yaml`. Si aucun emplacement ne
convient à un besoin, le blueprint officiel, sa documentation et ses tests
doivent évoluer avant la création d'un nouveau chemin.

Étape suivante : [créer l'entité Todo](02-create-entity.md).
