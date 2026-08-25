# Catalogue Des Capabilities

Une capability est une brique activable par `arclith-cli add-adapter`.

La section Capabilities est le niveau deep dive de la documentation. Elle
détaille les contrats, les adapters, les contraintes de production et les
validations. Le format attendu est décrit dans
[Structure d'une capability](capabilities/structure.md).

## Lire Le Catalogue

Le catalogue CLI est la source de vérité technique. Cette page sert de carte de
lecture et chaque ligne renvoie vers la fiche dédiée.

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

## Matrice

| Capability | Couche | Adapters | Quand la lire |
|---|---|---|---|
| [api](capabilities/api.md) | inbound | `fastapi` | exposer des endpoints HTTP |
| [mcp](capabilities/mcp.md) | inbound | `fastmcp` | exposer des tools MCP |
| [agent](capabilities/agent.md) | inbound | `langgraph` | exposer un agent LangGraph |
| [auth](capabilities/auth.md) | inbound | `keycloak` | sécuriser API ou MCP |
| [tenant](capabilities/tenant.md) | inbound | `vault` | résoudre un contexte tenant |
| [license](capabilities/license.md) | inbound | `role` | contrôler un droit d'accès |
| [probe](capabilities/probe.md) | inbound | `server` | exposer `/health` et `/ready` |
| [http](capabilities/http.md) | inbound | `idempotency`, `etag`, `cache-control` | durcir les conventions HTTP |
| [repository](capabilities/repository.md) | outbound | `memory`, `mongodb`, `duckdb`, `mariadb`, `postgresql` | persister les entités |
| [storage](capabilities/storage.md) | outbound | `filesystem`, `s3`, `azure-blob`, `gcs` | stocker fichiers et blobs |
| [cache](capabilities/cache.md) | outbound | `memory`, `redis` | partager JWKS, tenants et idempotence |
| [logger](capabilities/logger.md) | outbound | `console` | standardiser les logs |
| [secrets](capabilities/secrets.md) | outbound | `env`, `yaml`, `vault`, `chain` | résoudre les secrets |
| [llm](capabilities/llm.md) | outbound | `lmstudio`, `openai`, `anthropic` | configurer les modèles |
| [observability](capabilities/observability.md) | outbound | `langsmith`, `opentelemetry` | tracer runtime et agents |
| [command-bus](capabilities/command-bus.md) | bidirectional | `rabbitmq` | consommer et publier des commandes |
| [runtime](capabilities/runtime.md) | runtime | `docker-image` | générer le runtime conteneur |

## Parcours Fréquents

| Besoin | Lire |
|---|---|
| API minimale | [Quickstart API](quickstarts/api.md), [formation API](tutorials/todo-list/04-api.md), puis [api/fastapi](capabilities/api.md) |
| MCP minimal | [Quickstart MCP](quickstarts/mcp.md), [formation MCP](tutorials/todo-list/05-mcp.md), puis [mcp/fastmcp](capabilities/mcp.md) |
| Bus RabbitMQ | [Quickstart Bus](quickstarts/bus.md), puis [command-bus/rabbitmq](capabilities/command-bus.md) |
| Agent local | [Quickstart Agent](quickstarts/agent.md), [formation agent](tutorials/todo-list/06-agent.md), puis [agent/langgraph](capabilities/agent.md) |
| Fichiers et blobs | [storage](capabilities/storage.md), [quickstart filesystem](capabilities/storage/quickstart.md), puis [secrets](capabilities/secrets.md) pour les credentials |
| Service production | [Baseline production](production/baseline.md), puis les pages de la section Production |
| Déploiement | [Runtime Docker](runtime-docker.md), puis [Docker Compose](runtime-docker/docker-compose.md) |

## Ajouter Une Capability

Une PR qui ajoute ou modifie une capability doit mettre à jour :

1. le catalogue CLI ;
2. la page dédiée en respectant la [structure canonique](capabilities/structure.md) ;
3. cet index ;
4. le quickstart si le flux est fréquent ;
5. la formation associée quand un pas à pas est nécessaire ;
6. la baseline production si la capability appartient au socle de production ;
7. les captures, vidéos ou supports de formation quand la capability introduit
   un nouveau geste utilisateur.
