# Capability Observability

Observabilité du runtime, de l'API et des agents.

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

## Configuration

```yaml
# config/adapters/adapters.yaml
observability:
  enabled:
    - opentelemetry
    - langsmith
```

## Règle

LangSmith sert au banc de test agent. OpenTelemetry sert à l'observabilité transverse runtime/API.

## Validation

```bash
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local uv run pytest
```

## Suite

Lire [logger](logger.md) et [agent](agent.md).
