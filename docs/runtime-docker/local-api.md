# Lancement Local API

Objectif: lancer FastAPI depuis l'image Docker et valider le chemin complet `host -> conteneur ->
Arclith -> probes`.

## Configuration

FastAPI et les probes doivent écouter sur `0.0.0.0` dans le conteneur:

```yaml
# config/adapters/inbound/fastapi.yaml
host: 0.0.0.0
port: 8000
reload: false
```

```yaml
# config/adapters/inbound/probe.yaml
host: 0.0.0.0
port: 9000
enabled: true
```

Reconstruire l'image après toute modification de configuration embarquée:

```bash
uv lock
docker build -t my-service:local .
```

## Lancer En Mode Attaché

```bash
docker run --rm \
  -p 8000:8000 \
  -p 9000:9000 \
  my-service:local api
```

Dans un second terminal:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:9000/info
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

## Smoke Détaché

Utiliser ce smoke pour éviter la course au démarrage: `docker run -d` rend la main avant que
Uvicorn soit forcément prêt.

```bash
(
  set -eu

  API_CONTAINER_PORT="${API_CONTAINER_PORT:-8000}"
  API_HOST_PORT="${API_HOST_PORT:-$API_CONTAINER_PORT}"
  PROBE_CONTAINER_PORT="${PROBE_CONTAINER_PORT:-9000}"
  PROBE_HOST_PORT="${PROBE_HOST_PORT:-$PROBE_CONTAINER_PORT}"

  container_id="$(
    docker run --rm -d \
      -p "$API_HOST_PORT:$API_CONTAINER_PORT" \
      -p "$PROBE_HOST_PORT:$PROBE_CONTAINER_PORT" \
      my-service:local api
  )"
  cleanup() {
    docker stop "$container_id" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT

  for endpoint in "$PROBE_HOST_PORT/health" "$API_HOST_PORT/openapi.json"; do
    ready=0
    for _ in $(seq 1 30); do
      if curl -fsS "http://127.0.0.1:$endpoint" >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 1
    done

    if [ "$ready" -ne 1 ]; then
      docker logs "$container_id"
      exit 1
    fi
  done

  curl -fsS "http://127.0.0.1:$PROBE_HOST_PORT/health"
)
```

## Mapping De Ports

La partie droite de `-p host:container` doit correspondre au port configuré dans le conteneur.

Si FastAPI écoute dans le conteneur sur `8120`:

```bash
docker run --rm -p 8120:8120 -p 9000:9000 my-service:local api
curl -fsS http://127.0.0.1:8120/openapi.json >/dev/null
```

Pour publier ce même service sur le port host `8000`:

```bash
docker run --rm -p 8000:8120 -p 9000:9000 my-service:local api
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

## Durcissement Local

Une fois le smoke fonctionnel, tester le mode durci:

```bash
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  -p 8000:8000 \
  -p 9000:9000 \
  my-service:local api
```

## Checklist SOTA

- API et probes exposées séparément.
- `/health` valide le processus, `/ready` valide les dépendances.
- `reload: false` dans l'image.
- Logs sur stdout/stderr, pas de fichier de log local.
- Ports host et conteneur explicitement documentés.

Page suivante: [lancer le MCP localement](local-mcp.md).
