# 6.1 Configurer LM Studio et LangSmith

Intention: donner à l'agent un LLM local pour les décisions ambiguës et une observabilité LangSmith
pour inspecter les runs.

## LM Studio

Démarrer LM Studio Local Server sur `http://127.0.0.1:1234/v1`, puis vérifier les modèles:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Lancer le wizard LLM:

```bash
arclith-cli add-adapter --capability llm
```

Répondre:

```text
① Type d'adapter
   1  lmstudio
   2  openai
   3  anthropic

  Votre choix (numéro ou nom): 1

③ Paramètres lmstudio
  Model ID LM Studio: <model-id-lm-studio>
  Endpoint OpenAI-compatible LM Studio (http://127.0.0.1:1234/v1):
  API key LM Studio (lm-studio):

  Confirmer la génération ? [y/n] (y): y
```

Vérifier `config/adapters/outbound/lm.yaml`:

```yaml
provider: openai
model_name: "mistralai/ministral-3-3b"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
```

## LangSmith

LangSmith est optionnel pour exécuter localement, mais utile pour inspecter les runs.

Si vous travaillez hors ligne, conserver `observability.enabled: []` et passer directement à la
configuration LangGraph:

```dotenv
LANGGRAPH_CLI_NO_ANALYTICS=1
```

Sinon, ajouter LangSmith avec le profil de développement:

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --profile development
```

Répondre:

```text
① Type d'adapter
   1  langsmith
   2  opentelemetry

  Votre choix (numéro ou nom): 1
  Activer le tracing LangSmith [y/n] (y): y
  Projet LangSmith (todo-list-service): todo-list-service-dev
  Endpoint LangSmith (https://api.smith.langchain.com):
  Activer langsmith [y/n] (y): y
  Confirmer la génération ? [y/n] (y): y
```

Vérifier `config/adapters/outbound/langsmith.yaml`:

```yaml
project: "todo-list-service"
endpoint: "https://api.smith.langchain.com"
api_key_env: LANGSMITH_API_KEY
workspace_id_env: LANGSMITH_WORKSPACE_ID
tracing:
  enabled: true
  mode: otel
  sampling_rate: 1.0
studio: langgraph
langgraph_api_min_version: "0.11.0"
```

La CLI écrit uniquement les valeurs non secrètes dans `.env.example`. La clé est injectée dans le
runtime via `LANGSMITH_API_KEY`, jamais via un argument CLI ou dans Git. LangSmith sert à observer
l'agent:

- LangGraph exécute le graphe localement;
- LM Studio fournit le modèle local;
- LangSmith affiche les runs, les messages, les appels LLM et les erreurs.

Sans internet, LangGraph continue de tourner localement. L'inspection se fait alors avec
`http://127.0.0.1:2024/docs`, `/runs/stream` et `/threads/{thread_id}/state`.

![Flux LangGraph et LangSmith](assets/06-langsmith-flow.svg)

## LangGraph config

Vérifier `config/adapters/inbound/langgraph.yaml`:

```yaml
name: "todo_agent"
graph: "todo_agent"
entrypoint: "./src/todo_list_service/adapters/inbound/langgraph/agent.py:agent"
env: ".env"
```

Modifier `langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": {
    "todo_agent": "./src/todo_list_service/adapters/inbound/langgraph/agent.py:agent"
  },
  "env": ".env"
}
```

Pour prouver cette configuration avant de continuer, utiliser
[Validation IA locale et hors ligne](../../learning/local-ai-validation.md).

Étape suivante: [écrire les intent-interpreters](06-agent-intent-interpreters.md).
