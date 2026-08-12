# Lancement Local Autres Possibilités

Objectif: comprendre les autres modes runtime fournis par `arclith-run` et savoir quand les utiliser.

## Sélection Du Mode

Trois formes sont acceptées:

```bash
docker run --rm my-service:local api
docker run --rm -e ARCLITH_RUNTIME_MODE=mcp_http my-service:local
docker run --rm -e MODE=all my-service:local
```

Priorité:

1. `ARCLITH_RUNTIME_MODE`;
2. `MODE`;
3. premier argument de `docker run`;
4. `api` par défaut.

## Mode `all`

`all` lance l'API et le MCP HTTP dans le même conteneur si le `main.py` du projet le supporte.
C'est pratique pour une démonstration locale, mais il vaut mieux séparer les processus en production.

```bash
docker run --rm \
  -p 8000:8000 \
  -p 8001:8001 \
  -p 9000:9000 \
  my-service:local all
```

Vérifier:

```bash
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
curl -fsS http://127.0.0.1:9000/info
```

## Mode `mcp_sse`

Utiliser `mcp_sse` seulement si un client a besoin du transport SSE:

```bash
docker run --rm \
  -p 8001:8001 \
  -p 9000:9000 \
  my-service:local mcp_sse
```

Le transport recommandé pour les nouveaux clients reste `mcp_http` / streamable HTTP.

## Mode `bus`

`bus` lance un worker command-bus, typiquement RabbitMQ. Il faut d'abord ajouter l'adapter et écrire
le dispatcher/handler projet.

```bash
uv add "arclith[rabbitmq]"

arclith-cli add-adapter \
  --capability command-bus \
  --adapter rabbitmq \
  --param url=amqp://guest:guest@rabbitmq:5672/ \
  --param queue=arclith.commands \
  --param routing_key=commands \
  --yes
```

Lancer avec une URL RabbitMQ disponible depuis le conteneur:

```bash
docker run --rm \
  -e RABBITMQ_URL=amqp://guest:guest@host.docker.internal:5672/ \
  my-service:local bus
```

Le worker doit ack après succès métier, nack sans requeue sur erreur non récupérable, borner
`prefetch` et propager `correlation_id` / `traceparent`.

## Runtime Durci

Pour les modes non interactifs, tester aussi:

```bash
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  my-service:local bus
```

## Checklist SOTA

- `all` réservé au local ou à une démo.
- Production: un Deployment/processus par transport.
- Worker bus idempotent, borné et observable.
- URLs de dépendances configurées pour le réseau conteneur, pas pour le poste local.
- Arrêt propre: un processus principal, signaux Docker/Kubernetes propagés au runtime.

Page suivante: [Docker Compose](docker-compose.md).
