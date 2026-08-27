# Quickstart API

Créer un service et vérifier l'API locale.

## Prérequis

- Python 3.13
- `uv`

## Étapes

```bash
uvx --from arclith-cli arclith-cli init todo-api --dir .
cd todo-api
uv sync
MODE=api uv run python main.py
```

Dans un second terminal :

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:8000/docs
```

## Résultat

- `/health` retourne `{"status":"ok"}`.
- Swagger UI s'ouvre sur `/docs`.

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
