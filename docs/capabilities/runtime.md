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

## Propagation de trace du runtime durable

Les graphes construits avec `Arclith.langgraph()` transmettent automatiquement leur runtime
d'observabilité au serveur durable. Le même contrat fonctionne avec LangSmith, OpenTelemetry ou le
backend no-op; le runtime LangGraph n'importe aucun SDK fournisseur.

Les endpoints `runs/wait` et `runs/stream` filtrent le carrier HTTP par le propagateur configuré,
puis gardent ce contexte actif jusqu'à la fin réelle du graphe ou du flux SSE. Seuls
`langsmith-trace`, `traceparent`, `tracestate` et le baggage explicitement allowlisté peuvent entrer.
Les credentials, cookies et headers arbitraires sont ignorés et ne sont jamais écrits dans le
catalogue des runs.

Une span `langgraph.runtime.run` relie les deux services et expose seulement les identifiants
techniques `thread_id`, `run_id`, `assistant_id` et le statut du run. Les chemins succès, erreur,
déconnexion et annulation ferment tous le contexte dans un `finally`.

Le cycle de vie du serveur démarre, flush et ferme le runtime d'observabilité autour des ressources
PostgreSQL/Redis. Les probes `/health` et `/ready` restent indépendantes des exporters. Un graphe
compilé directement hors `Arclith.langgraph()` conserve le comportement no-op, sauf si un
`observability_runtime` explicite est fourni à `create_durable_langgraph_runtime_app()`.

Pour activer les traces avec le runtime durable, installer les extras séparément et sélectionner
l'adapter dans la configuration:

```bash
uv add "arclith[langgraph-runtime,langsmith]"
```

Voir [Observability](observability.md) pour la politique de capture, les allowlists et les profils.

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
