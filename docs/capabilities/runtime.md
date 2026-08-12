# Capability Runtime

Runtime de déploiement standardisé.

## Adapter

| Adapter | Usage |
|---|---|
| `docker-image` | `Dockerfile`, `.dockerignore`, `arclith-run` |

## Commande

```bash
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
```

## Fichiers Générés

```text
Dockerfile
.dockerignore
arclith-run
```

## Modes

| Mode | Commande interne |
|---|---|
| `api` | `MODE=api python main.py` |
| `mcp_http` | `MODE=mcp_http python main.py` |
| `bus` | `MODE=bus python main.py` |
| `agent` | `langgraph dev` ou `ARCLITH_AGENT_COMMAND` |

## Validation

```bash
docker build -t my-service:local .
docker run --rm -p 9000:9000 my-service:local api
curl -fsS http://127.0.0.1:9000/health
```

## Suite

Lire [Tutoriel Docker](../runtime-docker.md).
