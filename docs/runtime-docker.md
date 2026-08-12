# Tutoriel Docker Arclith

Ce parcours explique comment passer d'un projet Arclith local à une image Docker exploitable, puis
comment lancer cette même image en local, avec Docker Compose et avec Kubernetes.

L'idée directrice est simple: une seule image immutable, plusieurs processus au runtime. L'image
contient le code, les dépendances verrouillées et l'entrypoint `arclith-run`. Le choix du transport
se fait par argument (`api`, `mcp_http`, `mcp_sse`, `agent`, `bus`, `all`) ou par variable
`ARCLITH_RUNTIME_MODE` / `MODE`.

```text
image Docker Arclith
  -> arclith-run
  -> api | mcp_http | mcp_sse | agent | bus | all
  -> main.py ou LangGraph
```

## Parcours

1. [Build](runtime-docker/build.md): générer les fichiers runtime, préparer la configuration
   conteneur, construire et inspecter l'image.
2. [Lancement local API](runtime-docker/local-api.md): lancer FastAPI en conteneur, exposer
   `/openapi.json` et valider les probes.
3. [Lancement local MCP](runtime-docker/local-mcp.md): lancer FastMCP en `streamable-http` et
   vérifier l'accès client.
4. [Lancement local agent](runtime-docker/local-agent.md): lancer le runtime LangGraph/agent et
   gérer les variables LLM hors image.
5. [Lancement local autres possibilités](runtime-docker/local-other-modes.md): modes `all`,
   `mcp_sse`, `bus` et overrides runtime.
6. [Docker Compose](runtime-docker/docker-compose.md): orchestrer API, MCP, agent, worker et
   dépendances locales.
7. [Kubernetes](runtime-docker/kubernetes.md): déployer l'image en workloads séparés, avec probes,
   secrets, ressources et sécurité.

## Contrat Runtime

| Mode | Action |
|---|---|
| `api` | `MODE=api python main.py` |
| `mcp` / `mcp_http` | `MODE=mcp_http python main.py` |
| `mcp_sse` | `MODE=mcp_sse python main.py` |
| `bus` / `command_bus` / `command-bus` | `MODE=bus python main.py` |
| `agent` | `langgraph dev` ou `ARCLITH_AGENT_COMMAND` |
| `all` | `MODE=all python main.py` |

Les modes `bus`, `agent` et `all` supposent que le projet a bien les adapters, runners et
dépendances nécessaires. Arclith fournit le socle runtime; le projet garde la responsabilité de son
métier, de ses handlers et de son graphe.

## Principes SOTA

- Construire depuis un `uv.lock` à jour avec `uv sync --frozen`.
- Ne jamais injecter de secrets au build; utiliser l'environnement runtime, Docker secrets,
  Kubernetes Secret ou Vault.
- Garder un processus principal par conteneur en production. Réutiliser la même image avec des
  arguments différents plutôt que créer plusieurs images.
- Exposer les services conteneur sur `0.0.0.0`; réserver `127.0.0.1` aux lancements hors Docker.
- Valider `/health`, `/ready` et le endpoint métier exposé par le transport, pas seulement le fait
  que le conteneur soit `running`.
- Taguer les images avec une version immutable et, en déploiement, préférer un digest ou un tag de
  release à `latest`.
- Faire sortir logs et métriques sur les canaux standards: stdout/stderr, probes Arclith,
  OpenTelemetry si activé.

## Références Officielles

- [Docker build best practices](https://docs.docker.com/build/building/best-practices/)
- [Docker build secrets](https://docs.docker.com/build/building/secrets/)
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Kubernetes security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
