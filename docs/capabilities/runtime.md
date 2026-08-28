# Capability Runtime

Runtime de déploiement standardisé.

## Objectif

Générer une image unique capable de lancer les transports Arclith fréquents sans
rebuild: API, MCP, bus et agent.

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
| `agent` | `langgraph dev`, runtime durable Arclith ou `ARCLITH_AGENT_COMMAND` |

## Variables Utiles

| Variable | Usage |
|---|---|
| `MODE` | mode par défaut si aucun argument n'est passé |
| `ARCLITH_API_PORT` | port exposé API |
| `ARCLITH_MCP_PORT` | port exposé MCP |
| `ARCLITH_PROBE_PORT` | port probes |
| `ARCLITH_AGENT_PORT` | port LangGraph |
| `ARCLITH_AGENT_RUNTIME` | `development` (défaut) ou `durable` |
| `ARCLITH_AGENT_COMMAND` | commande agent personnalisée |

Le profil `durable` lance `arclith-agent-runtime` et requiert l'extra
`arclith[langgraph-runtime]`, PostgreSQL et Redis. Il conserve les threads et checkpoints sans clé
de licence LangGraph Cloud. Voir [Agent Persistence](agent-persistence.md) pour le contrat et les
limites de compatibilité.

## Règles

- Une image par service, plusieurs modes de lancement.
- Aucun secret dans les layers Docker.
- Utilisateur non-root dans l'image finale.
- Configuration et secrets injectés au runtime.
- Readiness vérifiée via `probe/server`.

## Validation

```bash
docker build -t my-service:local .
docker run --rm -d --name my-service -p 9000:9000 my-service:local api
curl -fsS http://127.0.0.1:9000/health
docker stop my-service
```

## Suite

Lire [Runtime et probes](../production/runtime.md), puis [Tutoriel Docker](../runtime-docker.md).
