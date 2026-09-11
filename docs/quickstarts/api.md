# Quickstart API

Créer un service, ajouter explicitement FastAPI, puis exposer un cas d'usage.

`init` ne crée aucun transport. `add-adapter` installe l'extra `arclith[fastapi]` et le
[blueprint FastAPI complet](../deep-dives/adapter-blueprints.md#fastapi) uniquement lorsque l'API
est choisie.

## Prérequis

- Python 3.13
- `uv`

Installer d'abord `arclith-cli` comme outil global géré par `uv`, puis vérifier que la commande est
disponible :

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
arclith-cli version
```

## Étapes

```bash
arclith-cli init todo-api --dir .
cd todo-api
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --entity Todo --yes
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
uv sync
```

Compléter ensuite les champs de `Todo` et `CreateTodoCommand`, implémenter
`CreateTodoUseCase.execute`, puis fournir cette instance au registre
`adapters.inbound.fastapi.bindings_generated.register` depuis le composition root. Cette liaison
reste explicite afin que le CLI n'invente ni repository ni politique transactionnelle.

Lancer l'API :

```bash
MODE=api uv run python main.py
```

Le `main.py` généré fournit l'API à Uvicorn sous forme de factory importable. Le réglage `reload`
de `config/adapters/inbound/fastapi.yaml` reste ainsi effectif en développement, sans importer
FastAPI avant l'ajout explicite de l'adapter.

Dans un second terminal :

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:8000/docs
```

## Résultat

- `/health` retourne `{"status":"ok"}`.
- Swagger UI s'ouvre sur `/docs` et la route liée apparaît après composition du use case.

## Erreur Fréquente

Si `/health` ne répond pas, le serveur n'est pas encore prêt ou le port `9000` est déjà pris.

## Média

!!! note "Média à produire"
    Capture : Swagger UI ouvert.
    Vidéo : création du projet puis appel `/health`.

## Suite

Lire [MCP](mcp.md), puis [api/fastapi](../capabilities/api.md). Pour exporter les traces et
métriques sans modifier le service, suivre
[OpenTelemetry de bout en bout](../capabilities/opentelemetry.md).
