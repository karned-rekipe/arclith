# Capability LLM

Configuration du modèle utilisé par les interpréteurs d'intention et agents.

## Objectif

`llm` configure le modèle utilisé par les adapters d'intelligence applicative:
interpréteur d'intention, agent LangGraph, classification, extraction ou aide à
la décision.

Le LLM reste un adapter outbound. Il peut proposer une action, structurer une
intention ou produire une réponse, mais l'écriture en base passe toujours par un
use case métier explicite.

## Adapters

| Adapter | Usage |
|---|---|
| `lmstudio` | modèle local OpenAI-compatible |
| `openai` | modèle OpenAI |
| `anthropic` | modèle Claude |

## Commandes

LM Studio local:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id>" \
  --yes
```

OpenAI:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter openai \
  --param model_name="<model-id>" \
  --param api_key="$OPENAI_API_KEY" \
  --yes
```

Anthropic:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter anthropic \
  --param model_name="<model-id>" \
  --param api_key="$ANTHROPIC_API_KEY" \
  --yes
```

## Configuration

LM Studio génère une configuration OpenAI-compatible:

```yaml
# config/adapters/outbound/lm.yaml
provider: openai
model_name: "<model-id>"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
```

Le `model_name` doit être l'identifiant exact retourné par LM Studio:

```bash
curl -fsS http://127.0.0.1:1234/v1/models | python -m json.tool
```

Ne pas inventer un alias comme `local-model` si LM Studio ne le déclare pas.

OpenAI garde la clé dans `.env` via un mapping de secret:

```yaml
# config/adapters/outbound/lm.yaml
provider: openai
model_name: "<model-id>"
api_key: ""
base_url: "https://api.openai.com/v1"
```

```dotenv
OPENAI_API_KEY=...
```

Anthropic suit le même principe:

```yaml
# config/adapters/outbound/lm.yaml
provider: anthropic
model_name: "<model-id>"
api_key: ""
```

```dotenv
ANTHROPIC_API_KEY=...
```

## Usage applicatif

Injecter le LLM dans un adapter outbound dédié, puis exposer au domaine une
interface stable comme `LLMPort`. Le use case garde la décision finale.

Exemple de règle:

```python
intent = await intent_interpreter.classify(message)
command = build_command_from_intent(intent)
result = await use_case.execute(command)
```

Éviter le chemin inverse où le prompt appelle directement le repository.

## Test Local Minimal

Avant de brancher l'agent, prouver que le modèle local répond:

```bash
curl -fsS http://127.0.0.1:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<model-id-lm-studio>",
    "messages": [
      {"role": "user", "content": "Réponds uniquement: ok"}
    ],
    "stream": false
  }' | python -m json.tool
```

Puis prouver que le client Python utilisé par Arclith sait parler à cet endpoint:

```bash
uv run --with langchain-openai python - <<'PY'
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="<model-id-lm-studio>",
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
    temperature=0,
)

print(llm.invoke("Réponds uniquement: ok").content)
PY
```

Depuis Docker, remplacer souvent `127.0.0.1` par `host.docker.internal`, car `localhost` désigne le
conteneur.

## Règles

Le LLM interprète ou assiste. Il n'écrit pas directement dans la persistance.

Le provider doit rester interchangeable. Ne pas exposer un type SDK OpenAI,
Anthropic ou Pydantic AI dans le domaine.

La clé API doit venir d'un secret ou de l'environnement, jamais d'un fichier
versionné avec une vraie valeur.

Les tests unitaires des use cases ne doivent pas dépendre du réseau. Utiliser un
fake de `LLMPort` pour les cas déterministes.

Documenter le `model_name` réellement utilisé par environnement, car les
résultats et les coûts changent avec le modèle.

## Validation

LM Studio:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Chat Completions local:

```bash
curl -fsS http://127.0.0.1:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model-id-lm-studio>","messages":[{"role":"user","content":"ok ?"}],"stream":false}'
```

Tests:

```bash
uv run pytest
```

Vérifier au minimum:

| Cas | Résultat attendu |
|---|---|
| provider OpenAI-compatible sans `base_url` | erreur de configuration |
| secret absent pour OpenAI ou Anthropic | erreur explicite |
| fake LLM en test unitaire | aucun appel réseau |
| agent hors ligne | `LANGSMITH_TRACING=false` et réponse via l'API LangGraph locale |
| agent avec observabilité active | traces visibles dans LangSmith |

## Suite

Lire aussi:

- [Capability Agent](agent.md)
- [Capability Observability](observability.md)
- [Validation IA locale](../learning/local-ai-validation.md)
- [Tutoriel agent](../tutorials/todo-list/06-agent-config.md)
