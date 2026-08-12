# Runtime Et Probes

Cette page définit le minimum pour lancer un service Arclith en conteneur.

## Objectif

Une même image doit pouvoir lancer API, MCP, bus ou agent sans rebuild.

## Stack Cible

| Besoin | Choix |
|---|---|
| Image | `runtime/docker-image` |
| Processus | `arclith-run` |
| Santé | `probe/server` |
| Sécurité | utilisateur non-root |
| Orchestration | Compose puis Kubernetes |

## Ajouter Les Adapters

```bash
arclith-cli add-adapter --capability probe --adapter server --yes
arclith-cli add-adapter --capability runtime --adapter docker-image --yes
```

## Modes De Lancement

```bash
docker run --rm -p 8000:8000 -p 9000:9000 my-service:local api
docker run --rm -p 8001:8001 -p 9000:9000 my-service:local mcp_http
docker run --rm -p 2024:2024 -p 9000:9000 my-service:local agent
```

## Règles

- Construire l'image une fois, configurer au runtime.
- Garder les secrets hors des layers Docker.
- Lancer le conteneur avec un utilisateur non-root.
- Définir CPU, mémoire, readiness et liveness en orchestration.
- Ne considérer un déploiement prêt qu'après une réponse positive de `/ready`.

## Vérifier

```bash
docker build -t my-service:local .
docker run --rm -d --name my-service -p 9000:9000 my-service:local api
curl -fsS http://127.0.0.1:9000/ready
docker stop my-service
```

## Suite

Lire le tutoriel [Docker](../runtime-docker.md), puis [Docker Compose](../runtime-docker/docker-compose.md).
