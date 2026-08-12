# Lancement Local Agent

Objectif: lancer le runtime agent/LangGraph depuis la même image Docker, sans intégrer de clés LLM
dans l'image.

## Prérequis Projet

Le mode `agent` nécessite:

- l'extra LangGraph dans le projet;
- un adapter `agent/langgraph`;
- un `langgraph.json`;
- les variables LLM et LangSmith injectées au runtime.

Préparer le projet:

```bash
uv add "arclith[langgraph]"

arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --param graph_name=my_agent \
  --yes
```

Si le projet utilise LM Studio ou un endpoint OpenAI-compatible lancé sur le poste, ne pas utiliser
`localhost` depuis le conteneur. Sur Docker Desktop, utiliser souvent:

```text
http://host.docker.internal:1234/v1
```

## Build

```bash
uv lock
docker build -t my-service:local .
```

## Lancer L'Agent

```bash
docker run --rm \
  --env-file .env.local \
  -e LANGGRAPH_HOST=0.0.0.0 \
  -e LANGGRAPH_PORT=2024 \
  -p 2024:2024 \
  my-service:local agent
```

`arclith-run agent` lance `langgraph dev` par défaut avec `--host 0.0.0.0`. Si le projet a besoin
d'une commande agent différente, utiliser `ARCLITH_AGENT_COMMAND`:

```bash
docker run --rm \
  --env-file .env.local \
  -e ARCLITH_AGENT_COMMAND='langgraph dev --host 0.0.0.0 --port 2024 --no-browser --allow-blocking' \
  -p 2024:2024 \
  my-service:local agent
```

## Vérifier

Ouvrir LangSmith Studio ou le client agent sur:

```text
http://127.0.0.1:2024
```

Pour une validation complète, déclencher un run avec un `thread_id` durable et vérifier que le graphe
appelle bien les ports/use cases du projet. Le conteneur qui expose l'agent ne doit pas écrire en
base directement depuis le LLM.

## Secrets

Ne jamais écrire ces valeurs dans le Dockerfile:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
LANGSMITH_API_KEY
MONGODB_URI
VAULT_TOKEN
```

Utiliser un fichier local non commité:

```bash
cp .env.example .env.local
chmod 0600 .env.local
```

Puis injecter:

```bash
docker run --rm --env-file .env.local my-service:local agent
```

## Checklist SOTA

- LLM comme adapter outbound, jamais comme accès direct à la persistance.
- Variables LLM injectées au runtime uniquement.
- `host.docker.internal` utilisé quand le modèle tourne sur le poste hôte.
- Traces LangSmith/OpenTelemetry activées par configuration, pas par code métier.
- En production, remplacer `langgraph dev` par la commande serveur validée du projet via
  `ARCLITH_AGENT_COMMAND` si nécessaire.

Page suivante: [autres modes locaux](local-other-modes.md).
