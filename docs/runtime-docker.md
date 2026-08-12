# Runtime Docker Arclith

## Objectif

`runtime/docker-image` standardise une image Docker Arclith unique pour plusieurs transports. Le
choix du processus se fait au runtime par argument d'entrypoint, `ARCLITH_RUNTIME_MODE` ou `MODE`;
il ne nécessite pas de rebuild.

```text
docker image
  -> arclith-run
  -> MODE=api | mcp_http | mcp_sse | bus | agent | all
  -> main.py ou LangGraph
```

Le framework ne génère pas de logique métier. Le projet reste responsable des runners déclarés dans
`main.py`, des handlers RabbitMQ et du graphe LangGraph.

## Génération

Les projets créés par `arclith-cli init` incluent déjà `Dockerfile`, `.dockerignore` et
`arclith-run`. Pour ajouter ou régénérer ces fichiers dans un projet existant:

```bash
arclith-cli add-adapter \
  --capability runtime \
  --adapter docker-image \
  --param api_port=8000 \
  --param mcp_port=8001 \
  --param probe_port=9000 \
  --param agent_port=2024 \
  --yes
```

Fichiers générés:

```text
Dockerfile
.dockerignore
arclith-run
```

## Build Déterministe

Le Dockerfile est multi-stage:

- `builder`: installe `uv`, lit `pyproject.toml` et `uv.lock`, puis exécute `uv sync --frozen`.
- `runtime`: repart d'une image Python 3.13 slim, copie uniquement l'environnement virtuel et le
  contexte filtré par `.dockerignore`, puis lance sous l'utilisateur non-root `1001:1001`.

Avant de construire l'image, verrouiller les dépendances:

```bash
uv lock
docker build -t my-service:local .
```

Les dépendances optionnelles sont gouvernées par le `pyproject.toml` du projet. Pour une image qui
doit lancer un worker RabbitMQ ou un agent LangGraph, ajouter les extras correspondants avant le
lock:

```bash
uv add "arclith[rabbitmq]"
uv add "arclith[langgraph]"
uv lock
```

## Modes Runtime

L'entrypoint accepte un argument explicite:

```bash
docker run --rm -p 8000:8000 -p 9000:9000 my-service:local api
docker run --rm -p 8001:8001 -p 9000:9000 my-service:local mcp_http
docker run --rm --env MODE=all -p 8000:8000 -p 8001:8001 -p 9000:9000 my-service:local
docker run --rm --env ARCLITH_RUNTIME_MODE=bus my-service:local
docker run --rm -p 2024:2024 my-service:local agent
```

Contrat des modes:

| Mode | Action |
|---|---|
| `api` | `MODE=api python main.py` |
| `mcp` / `mcp_http` | `MODE=mcp_http python main.py` |
| `mcp_sse` | `MODE=mcp_sse python main.py` |
| `bus` / `command_bus` / `command-bus` | `MODE=bus python main.py` |
| `agent` | `langgraph dev` ou `ARCLITH_AGENT_COMMAND` |
| `all` | `MODE=all python main.py` |

`api` est le `CMD` par défaut. Les modes `bus`, `mcp_*` et `all` supposent que `main.py` les
implémente. Le mode `agent` utilise `langgraph.json`; si le projet a besoin d'un serveur agent
différent, définir `ARCLITH_AGENT_COMMAND`.

## Probes Et Healthcheck

Le Dockerfile expose par défaut:

- `8000`: FastAPI.
- `8001`: FastMCP.
- `9000`: probes Arclith.
- `2024`: LangGraph local server.

Le `HEALTHCHECK` interroge `/health` sur `ARCLITH_PROBE_PORT`, `9000` par défaut:

```bash
container_id="$(docker run --rm -d -p 8000:8000 -p 9000:9000 my-service:local api)"
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:9000/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:9000/health
docker stop "$container_id"
```

## Secrets

Aucun secret ne doit être fourni au build. Ne pas utiliser `ARG` ou `ENV` pour des tokens,
mots de passe ou clés privées dans le Dockerfile. Fournir les secrets au runtime:

- variables d'environnement injectées par l'orchestrateur;
- Docker secrets montés en fichiers;
- Vault ou adapter `secrets/chain`;
- fichiers montés hors image, jamais copiés dans les layers.

Le `.dockerignore` généré exclut notamment `.env`, `secrets.yaml`, les clés privées, `.venv`,
les caches et les artefacts de couverture.

## Compose Et Kubernetes

En Compose, préférer l'argument d'entrypoint et `depends_on.condition: service_healthy` pour les
dépendances locales:

```yaml
services:
  api:
    image: my-service:local
    command: ["api"]
    ports:
      - "8000:8000"
      - "9000:9000"

  worker:
    image: my-service:local
    command: ["bus"]
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/
    depends_on:
      rabbitmq:
        condition: service_healthy
```

En Kubernetes, garder la même image et changer seulement `args`:

```yaml
containers:
  - name: api
    image: my-service:local
    args: ["api"]
```

## Validation Locale

Le smoke Docker ne pousse aucune image. Il attend explicitement que les probes soient disponibles,
car `docker run -d` rend la main avant que Uvicorn ait terminé son démarrage:

```bash
(
  set -eu

  uv lock
  docker build -t my-service:local .

  container_id="$(docker run --rm -d -p 8000:8000 -p 9000:9000 my-service:local api)"
  cleanup() {
    docker stop "$container_id" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT

  ready=0
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:9000/health >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done

  if [ "$ready" -ne 1 ]; then
    docker logs "$container_id"
    exit 1
  fi

  curl -fsS http://127.0.0.1:9000/health
)
```
