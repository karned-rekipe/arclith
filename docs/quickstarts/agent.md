# Quickstart Agent

Ajouter un agent LangGraph minimal à un service.

## Prérequis

- Python 3.13
- `uv`
- LM Studio si tu utilises un LLM local

## Étapes

Si tu n'as pas encore de projet :

```bash
uvx --from arclith-cli arclith-cli init todo-agent --dir .
cd todo-agent
uv sync
```

```bash
uv add "arclith[langgraph]"
uvx --from arclith-cli arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --yes
```

Pour un LLM local :

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id-lm-studio>" \
  --yes
```

## Validation

```bash
export LANGSMITH_TRACING=false
export LANGGRAPH_CLI_NO_ANALYTICS=1
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Dans un second terminal:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Réponds uniquement: ok"}
      ]
    },
    "stream_mode": "values"
  }'
```

Pour inspecter l'état après le run, utiliser un thread:

```bash
THREAD_ID=$(curl -fsS -X POST "http://127.0.0.1:2024/threads" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

curl -N -X POST "http://127.0.0.1:2024/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"agent","input":{"messages":[{"role":"human","content":"Réponds uniquement: ok"}]},"stream_mode":"values"}'

curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
```

## Résultat

L'Agent Server local répond sur `http://127.0.0.1:2024`. La documentation API locale est disponible
sur `http://127.0.0.1:2024/docs`.

LangGraph Studio détecte aussi le graphe généré depuis `langgraph.json`, mais son UI hébergée
nécessite un accès internet. Hors ligne, la validation se fait par API ou SDK.

Le graphe généré est volontairement minimal. Le projet remplace ensuite l'état, les nœuds et les
transitions pour appeler ses use cases.

## Média

!!! note "Média à produire"
    Capture : terminal avec `langgraph dev` et réponse API.
    Vidéo : ajout agent, lancement local, premier run API, puis Studio si internet disponible.

## Suite

Lire [agent/langgraph](../capabilities/agent.md), [Validation IA locale](../learning/local-ai-validation.md),
puis le [parcours Todo agent](../tutorials/todo-list/06-agent.md).
