# 1. Initialiser le projet

Objectif: créer uniquement le projet Arclith minimal, sans entité métier et sans CRUD généré.

![Capture interactive init](assets/01-init-project.svg)

Depuis le dossier qui contiendra les projets de test:

```bash
mkdir -p ~/Perso/projets/demo-arclith
cd ~/Perso/projets/demo-arclith

uv tool upgrade arclith-cli
arclith-cli init
```

Répondre au prompt:

```text
Projet (ex : my-recipe-service, meal-planner)
  Nom du projet: todo-list-service
```

Entrer dans le projet et installer les dépendances:

```bash
cd todo-list-service
uv sync
```

Ce tutoriel nécessite `arclith-cli>=0.11.0`, qui génère une dépendance
`arclith>=0.14.0`. Ces versions utilisent uniquement le nouveau format
`observability.enabled`.

Le projet démarre avec `repository: memory`:

```yaml
# config/adapters/adapters.yaml
logger: console
repository: memory
observability:
  enabled: []
```

La structure attendue est:

```text
todo-list-service/
  config/
  src/todo_list_service/
    domain/
    application/
    adapters/
    infrastructure/
  tests/
  main.py
  pyproject.toml
```

## Tester

Le scaffold minimal contient un test de bootstrap:

```bash
uv run python -m pytest
```

Résultat attendu:

```text
tests/test_project_bootstrap.py ..   [100%]
```

## Voie rapide

```bash
uv tool upgrade arclith-cli
arclith-cli init todo-list-service
cd todo-list-service
uv sync
uv run python -m pytest
```

Étape suivante: [créer l'entité Todo](02-create-entity.md).
