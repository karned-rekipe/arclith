# Quickstart API

Créer un service, ajouter explicitement FastAPI, puis exposer un cas d'usage.

`init` ne crée aucun transport. `add-adapter` installe l'extra `arclith[fastapi]` et le
[blueprint FastAPI complet](../deep-dives/adapter-blueprints.md#fastapi) uniquement lorsque l'API
est choisie.

## Prérequis

- Python 3.13 ;
- [`uv`](https://docs.astral.sh/uv/).

Installer d'abord `arclith-cli` comme outil global géré par `uv`, puis vérifier que la commande est
disponible :

```bash
uv tool install arclith-cli
arclith-cli version
```

## Étapes

```bash
arclith-cli init todo-api --dir .
cd todo-api
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability api --adapter fastapi \
  --param port=8765 --param reload=false --yes
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
uv sync
```

Le service est déjà fonctionnel avec les seuls champs techniques de `Entity` :
`CreateTodoUseCase` construit l'entité, la persiste via `Repository[Todo]` et la
composition générée l'injecte dans le binding. Ajouter ensuite les mêmes champs
métier validés à `Todo` et `CreateTodoCommand`. Une composition plus riche qu'un
repository unique doit rester explicite dans l'infrastructure.

Lancer l'API :

```bash
MODE=api uv run python main.py
```

Le `main.py` généré fournit l'API à Uvicorn sous forme de factory importable. Le réglage `reload`
de `config/adapters/inbound/fastapi.yaml` reste ainsi effectif en développement, sans importer
FastAPI avant l'ajout explicite de l'adapter.

Dans un second terminal :

```bash
curl -fsS http://127.0.0.1:8765/openapi.json
curl -fsS -X POST http://127.0.0.1:8765/v1/todos \
  -H 'content-type: application/json' -d '{}'
```

## Résultat

- Swagger UI s'ouvre sur `http://127.0.0.1:8765/docs`.
- OpenAPI contient exactement une opération `POST /v1/todos`.
- La création retourne `201` avec `uuid`, dates d'audit et `version`, même sans
  champ métier supplémentaire.

## Erreur Fréquente

Si l'API ne répond pas, vérifier que le port choisi est libre et que
`config/adapters/inbound/fastapi.yaml` contient le même port. Les endpoints de
probe ne sont présents qu'après ajout explicite de la capability `probe`.

## Média

!!! note "Média à produire"
    Capture : Swagger UI ouvert.
    Vidéo : création du projet puis appel `/health`.

## Suite

Lire [MCP](mcp.md), puis [api/fastapi](../capabilities/api.md). Pour exporter les traces et
métriques sans modifier le service, suivre
[OpenTelemetry de bout en bout](../capabilities/opentelemetry.md).
