# Observabilité Production

Cette page donne le minimum pour diagnostiquer un service Arclith en production.

## Objectif

Chaque requête API, appel MCP, message bus ou run agent doit pouvoir être relié
à un trace id, un service et un environnement.

## Stack Cible

| Besoin | Choix |
|---|---|
| Traces runtime/API | OpenTelemetry |
| Traces agent | LangSmith |
| Logs | logger structuré |
| Santé | probes HTTP |
| Corrélation | `traceparent` |

## Ajouter Les Adapters

```bash
arclith-cli add-adapter --capability observability --adapter opentelemetry --yes
arclith-cli add-adapter --capability observability --adapter langsmith --yes
arclith-cli add-adapter --capability logger --adapter loguru --yes
arclith-cli add-adapter --capability probe --adapter server --yes
```

## Variables Minimales

```bash
export OTEL_SERVICE_NAME=my-service
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production
```

## Règles

- Nommer explicitement le service et l'environnement.
- Propager `traceparent` entre API, MCP, bus et agent.
- Ne pas logger les secrets, tokens ou payloads sensibles.
- Exposer `/health` et `/ready` sur un port de probe dédié.
- Garder LangSmith optionnel si aucun agent n'est lancé.

## Vérifier

```bash
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local uv run pytest
curl -fsS http://127.0.0.1:9000/health
```

## Suite

Lire [runtime et probes](runtime.md), puis les capabilities [observability](../capabilities/observability.md) et [logger](../capabilities/logger.md).
