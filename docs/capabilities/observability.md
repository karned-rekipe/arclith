# Capability Observability

Observabilité du runtime, de l'API et des agents.

## Objectif

Produire les signaux nécessaires pour relier une requête, un tool MCP, une
commande RabbitMQ et un run agent.

## Adapters

| Adapter | Usage |
|---|---|
| `langsmith` | traces et runs agents LangGraph |
| `opentelemetry` | traces et métriques OTLP |

## Commande

```bash
arclith-cli add-adapter --capability observability --adapter opentelemetry --yes
arclith-cli add-adapter --capability observability --adapter langsmith --yes
```

## Activation

```yaml
# config/adapters/adapters.yaml
observability:
  enabled:
    - opentelemetry
    - langsmith
```

## OpenTelemetry

```yaml
# config/adapters/outbound/opentelemetry.yaml
service_name: "my-service"
endpoint: "http://localhost:4318"
protocol: "http/protobuf"
traces: true
metrics: false
instrument_fastapi: true
```

## LangSmith

```yaml
# config/adapters/outbound/langsmith.yaml
tracing: true
project: "my-service-dev"
endpoint: "https://api.smith.langchain.com"
api_key_env: LANGSMITH_API_KEY
```

## Règles

- OpenTelemetry sert au runtime, API, métriques et corrélation.
- LangSmith sert aux runs agents et aux évaluations.
- Définir `service.name`, `service.version` et l'environnement.
- Propager `traceparent` entre HTTP, MCP, bus et agent.
- Ne jamais envoyer de secret dans logs, traces ou attributs.

## Validation

```bash
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local uv run pytest
```

## Suite

Lire [Observabilité production](../production/observability.md), [logger](logger.md) et [agent](agent.md).
