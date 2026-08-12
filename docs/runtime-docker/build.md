# Docker Build

Objectif: produire une image Docker Arclith déterministe, minimale et réutilisable pour tous les
transports du service.

## Prérequis

- Docker Desktop ou un moteur Docker compatible BuildKit.
- Python 3.13 et `uv` côté poste.
- Un projet Arclith avec `pyproject.toml`, `uv.lock`, `main.py`, `config/` et `src/`.

Pour créer un projet de test:

```bash
uvx --from arclith-cli arclith-cli init my-service --dir .
cd my-service
uv sync
uv run pytest
```

## Générer Le Runtime Docker

Les projets créés par `arclith-cli init` incluent déjà:

```text
Dockerfile
.dockerignore
arclith-run
```

Pour ajouter ou régénérer ces fichiers dans un projet existant:

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

Le Dockerfile généré suit ce contrat:

- build multi-stage à partir de `python:3.13-slim-bookworm`;
- installation des dépendances par `uv sync --frozen`;
- copie de `.venv` depuis le stage builder;
- exécution non-root en `1001:1001`;
- exclusion de `.env`, `secrets.yaml`, clés privées, tests, docs et caches via `.dockerignore`;
- `HEALTHCHECK` sur `/health` du serveur de probes.

## Préparer La Configuration Conteneur

Dans un conteneur, un service publié doit écouter sur `0.0.0.0`. `127.0.0.1` signifie "loopback
du conteneur" et n'est pas accessible via `docker run -p`.

Créer ou vérifier les fichiers suivants avant le build:

```bash
arclith-cli add-adapter \
  --capability api \
  --adapter fastapi \
  --param host=0.0.0.0 \
  --param port=8000 \
  --param reload=false \
  --yes

arclith-cli add-adapter \
  --capability mcp \
  --adapter fastmcp \
  --param host=0.0.0.0 \
  --param port=8001 \
  --yes
```

Le reload FastAPI doit rester désactivé dans une image runtime. Le rechargement automatique est un
outil de développement local, pas un comportement de conteneur.

## Verrouiller Et Construire

```bash
uv lock
docker build -t my-service:local .
```

Pour préparer une publication registry, utiliser un tag explicite:

```bash
VERSION=0.1.0
IMAGE=ghcr.io/karned-rekipe/my-service:$VERSION

docker build -t "$IMAGE" .
docker image inspect "$IMAGE" --format '{{.Id}} {{.Config.User}}'
```

Le résultat attendu doit montrer un utilisateur non-root, par exemple `1001:1001`.

## Inspection Locale

Vérifier que l'image ne contient pas les fichiers à risque:

```bash
docker run --rm --entrypoint sh my-service:local -lc 'id && test ! -f .env && test ! -f secrets.yaml'
docker history my-service:local
```

Inspecter les ports exposés:

```bash
docker image inspect my-service:local \
  --format '{{json .Config.ExposedPorts}}'
```

## Publication

Publier seulement après validation locale:

```bash
docker push "$IMAGE"
```

En production, préférer ensuite le digest:

```bash
docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}'
```

## Checklist SOTA

- `uv.lock` commité et synchronisé avec `pyproject.toml`.
- Aucune clé, aucun token et aucun fichier `.env` dans le contexte final.
- Image lancée en non-root.
- Ports conteneur alignés avec `config/adapters/inbound/*.yaml`.
- Tag immutable ou digest pour les déploiements.
- Build reproductible en CI avec les mêmes commandes que localement.
- Couches ordonnées pour préserver le cache: dépendances avant code applicatif, contexte réduit par
  `.dockerignore`.

Page suivante: [lancer l'API localement](local-api.md).
