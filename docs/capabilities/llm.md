# Capability LLM

Configuration du modèle utilisé par les interpréteurs d'intention et agents.

## Adapters

| Adapter | Usage |
|---|---|
| `lmstudio` | modèle local OpenAI-compatible |
| `openai` | modèle OpenAI |
| `anthropic` | modèle Claude |

## Commande

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id>" \
  --yes
```

## Configuration

```yaml
# config/adapters/outbound/lm.yaml
provider: openai
model_name: "<model-id>"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
```

## Règle

Le LLM interprète ou assiste. Il n'écrit pas directement dans la persistance.

## Validation

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

## Suite

Lire [agent/langgraph](agent.md).
