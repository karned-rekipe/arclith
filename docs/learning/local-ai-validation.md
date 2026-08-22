# Validation IA Locale Et Hors Ligne

Objectif: prouver rapidement qu'un LLM local, un adapter LLM Arclith et un agent LangGraph
fonctionnent, même sans LangSmith ni accès internet.

## Modèle Mental

Trois composants sont séparés:

```text
client local, curl, UI ou test
  -> Agent Server LangGraph :2024
  -> adapter LLM Arclith / ChatOpenAI
  -> LM Studio :1234/v1
```

LM Studio sert le modèle. LangGraph orchestre le graphe. Arclith garde le métier dans les ports et
use cases.

Ne pas confondre:

| Besoin | Surface |
| --- | --- |
| tester que le modèle local répond | LM Studio `:1234/v1` |
| tester que le graphe agent répond | LangGraph `:2024` |
| inspecter un thread durable | API LangGraph `/threads/...` |
| tracer dans LangSmith | optionnel, nécessite réseau et clé |
| utiliser LM Studio Chat comme interface | possible via MCP, pas via `:2024` directement |

## Préparer Le Mode Hors Ligne

Pour un test strictement local:

```bash
unset LANGSMITH_API_KEY LANGCHAIN_API_KEY
export LANGSMITH_TRACING=false
export LANGGRAPH_CLI_NO_ANALYTICS=1
```

Si le projet charge `.env`, conserver les mêmes valeurs dans `.env.local` ou `.env`:

```dotenv
LANGSMITH_TRACING=false
LANGGRAPH_CLI_NO_ANALYTICS=1
```

LangGraph Studio charge une interface hébergée depuis `smith.langchain.com`. Hors ligne, utiliser
l'API locale, le SDK Python ou une petite UI locale.

## Tester LM Studio

Démarrer le serveur local LM Studio sur `http://127.0.0.1:1234/v1`, puis vérifier les modèles:

```bash
curl -fsS http://127.0.0.1:1234/v1/models | python -m json.tool
```

Recopier le `id` exact du modèle chargé. Un alias inventé comme `local-model` peut être refusé par
LM Studio.

Tester une complétion minimale:

```bash
curl -fsS http://127.0.0.1:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistralai/ministral-3-3b",
    "messages": [
      {"role": "user", "content": "Réponds uniquement: ok"}
    ],
    "stream": false
  }' | python -m json.tool
```

Remplacer `mistralai/ministral-3-3b` par l'identifiant retourné par `/v1/models`.

## Tester L'Adapter LLM Arclith

Installer et configurer l'adapter:

```bash
uv add "arclith[langgraph]"

arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id-lm-studio>" \
  --yes
```

Vérifier la configuration:

```yaml
# config/adapters/outbound/lm.yaml
provider: openai
model_name: "<model-id-lm-studio>"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
```

Tester le client OpenAI-compatible depuis Python:

```bash
uv run --with langchain-openai python - <<'PY'
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="<model-id-lm-studio>",
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
    temperature=0,
)

response = llm.invoke("Réponds uniquement: ok")
print(response.content)
PY
```

Ce test prouve que le modèle local, l'endpoint OpenAI-compatible et la dépendance Python sont
cohérents. Les tests unitaires métier doivent rester sur un fake de port LLM.

## Tester LangGraph Sans Studio

Lancer l'Agent Server local:

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Le serveur expose une API locale:

```text
http://127.0.0.1:2024
http://127.0.0.1:2024/docs
```

Tester un run stateless:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "todo_agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Quelles sont mes tâches en cours ?"}
      ]
    },
    "stream_mode": "values"
  }'
```

Le `assistant_id` doit correspondre au nom déclaré dans `langgraph.json`.

## Inspecter Un Thread Durable

Pour pouvoir relire l'état final, créer un thread explicite:

```bash
THREAD_ID=$(curl -fsS -X POST "http://127.0.0.1:2024/threads" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

echo "$THREAD_ID"
```

Lancer le run dans ce thread:

```bash
curl -N -X POST "http://127.0.0.1:2024/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "todo_agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Quelles sont mes tâches en cours ?"}
      ]
    },
    "stream_mode": "values"
  }'
```

Relire l'état et les runs:

```bash
curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/runs" | python -m json.tool
```

Utiliser `stream_mode: "values"` ou `"updates"` pour apprendre le graphe. `messages-tuple` est utile
pour le streaming fin des messages, mais il est moins lisible au début.

## Tester Avec Le SDK Python

```bash
uv run --with langgraph-sdk python - <<'PY'
from langgraph_sdk import get_sync_client

client = get_sync_client(url="http://127.0.0.1:2024")

state = client.runs.wait(
    None,
    "todo_agent",
    input={
        "messages": [
            {"role": "human", "content": "Quelles sont mes tâches en cours ?"}
        ]
    },
)

print(state)
PY
```

Ce chemin est le plus pratique pour écrire un smoke test local automatisé.

## LM Studio Chat Et LangGraph

LM Studio Chat ne se branche pas directement sur `http://127.0.0.1:2024`, car l'Agent Server
LangGraph n'expose pas une API Chat Completions. Deux chemins sont possibles:

```text
recommande:
client -> LangGraph :2024 -> adapter LLM -> LM Studio :1234/v1

possible:
LM Studio Chat -> serveur MCP local -> LangGraph :2024
```

Le pont MCP est utile pour tester une ergonomie chat locale, mais LangGraph devient alors un tool
appelé par LM Studio. Ce n'est pas le même modèle que LangGraph orchestrateur principal.

## Architecture Microservice

En développement, un seul `langgraph dev` peut exposer plusieurs graphes depuis `langgraph.json`.

En production, découper selon le bounded context:

- agent proche du service si l'agent manipule un domaine précis;
- agent central si l'assistant orchestre plusieurs domaines;
- jamais d'accès direct depuis l'agent central aux repositories ou bases des autres services.

Un agent central appelle les APIs, events ou tools MCP des microservices. Les use cases restent
propriétaires de leur métier.

## Checklist

- `/v1/models` retourne le `model id` local.
- `/v1/chat/completions` répond avec ce `model id`.
- `config/adapters/outbound/lm.yaml` utilise le même `model_name`.
- `LANGSMITH_TRACING=false` est actif pour un test hors ligne.
- `langgraph dev --no-browser --allow-blocking --port 2024` démarre.
- un run `values` répond via `/runs/stream`.
- un thread explicite peut être relu via `/threads/{thread_id}/state`.
- les tests unitaires importants utilisent un fake LLM.

## Sources

- LM Studio local server: <https://lmstudio.ai/docs/developer/core/server>
- LM Studio OpenAI-compatible: <https://lmstudio.ai/docs/developer/openai-compat>
- LM Studio MCP: <https://lmstudio.ai/docs/app/mcp>
- LangGraph local server: <https://docs.langchain.com/oss/python/langgraph/local-server>
