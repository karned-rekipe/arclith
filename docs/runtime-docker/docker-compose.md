# Lancement Via Docker Compose

Objectif: orchestrer plusieurs transports Arclith et leurs dépendances locales avec une seule image.

Compose est adapté au développement intégré, aux démonstrations et aux environnements single-node.
Pour la production scalable, passer à Kubernetes ou à un orchestrateur équivalent.

## Fichier Compose Minimal

```yaml
x-arclith-service: &arclith-service
  image: my-service:local
  build: .

services:
  api:
    <<: *arclith-service
    command: ["api"]
    ports:
      - "8000:8000"
      - "9000:9000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"
      interval: 10s
      timeout: 3s
      retries: 6
      start_period: 15s

  mcp:
    <<: *arclith-service
    command: ["mcp_http"]
    ports:
      - "8001:8001"
      - "9001:9000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"
      interval: 10s
      timeout: 3s
      retries: 6
      start_period: 15s
```

Lancer:

```bash
docker compose up --build
```

Vérifier depuis le poste:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9001/health
```

## Ajouter MongoDB Et RabbitMQ

```yaml
x-arclith-service: &arclith-service
  image: my-service:local
  build: .

services:
  api:
    <<: *arclith-service
    command: ["api"]
    environment:
      MONGODB_URI: mongodb://mongo:27017/
    depends_on:
      mongo:
        condition: service_healthy
    ports:
      - "8000:8000"
      - "9000:9000"

  worker:
    <<: *arclith-service
    command: ["bus"]
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/
      MONGODB_URI: mongodb://mongo:27017/
    depends_on:
      rabbitmq:
        condition: service_healthy
      mongo:
        condition: service_healthy

  mongo:
    image: mongo:8
    volumes:
      - mongo-data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 10s
      timeout: 5s
      retries: 10

  rabbitmq:
    image: rabbitmq:4-management
    ports:
      - "15672:15672"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  mongo-data:
```

## Réseaux Et Exposition

Par défaut, Compose crée un réseau privé par projet. Exposer sur le host uniquement les transports
utiles à l'humain ou au client externe:

- API: `8000`;
- MCP: `8001`;
- probes API/MCP: `9000`, `9001`;
- RabbitMQ management local: `15672`, seulement si nécessaire.

Les dépendances internes utilisent les noms de services: `mongo`, `rabbitmq`, `api`, `mcp`.

## Secrets

Pour un usage local, un fichier `.env.local` non commité est acceptable:

```yaml
services:
  api:
    env_file:
      - .env.local
```

Pour un usage plus proche production, préférer des secrets Compose montés en fichiers et un adapter
de secrets Arclith capable de les lire.

```yaml
services:
  api:
    secrets:
      - mongodb-uri

secrets:
  mongodb-uri:
    file: ./secrets/mongodb-uri.txt
```

Compose monte les secrets dans `/run/secrets/<nom>`. Le projet doit ensuite lire ce fichier via son
resolver de secrets, plutôt que supposer une variable d'environnement en clair.

## Checklist SOTA

- `depends_on.condition: service_healthy` pour les dépendances critiques.
- Données persistantes dans des volumes nommés.
- Probes par service, pas seulement sur l'API.
- Ports host limités au strict nécessaire.
- Même image pour API, MCP, agent et worker; seul `command` change.
- Secrets hors image et hors dépôt.

Page suivante: [Kubernetes](kubernetes.md).
