# Capability Observability

Arclith fournit une observabilité optionnelle aux frontières sans introduire de SDK fournisseur
dans le domaine ou les use cases.

## Adapters

| Adapter | Usage |
|---|---|
| `langsmith` | traces agents, contexte distribué et API avancées LangSmith |
| `opentelemetry` | traces et métriques OTLP du runtime |

Sans adapter activé, `arclith.tracer()` retourne un tracer no-op. Le code applicatif reste donc
identique avec ou sans backend.

## Installer et activer LangSmith

L'installation, l'activation et l'émission sont trois décisions indépendantes:

```bash
uv add "arclith[langsmith]"

arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --profile development \
  --yes
```

La commande:

- ajoute l'extra `arclith[langsmith]` idempotemment;
- génère `config/adapters/outbound/langsmith.yaml`;
- ajoute `langsmith` à `observability.enabled`;
- génère uniquement les valeurs non secrètes dans `.env.example`;
- ajoute `.env` à `.gitignore`;
- ne demande et n'écrit jamais la clé API.

Copier les valeurs utiles de `.env.example` vers le secret store du runtime, puis définir:

```bash
export LANGSMITH_API_KEY="<secret>"
```

Si LangSmith n'est pas souhaité sur un environnement, ne pas le placer dans
`adapters.observability.enabled`. Aucun module LangSmith, client, buffer ou appel réseau n'est alors
créé.

## Configuration complète

```yaml
# config/adapters/adapters.yaml
observability:
  enabled:
    - langsmith
```

```yaml
# config/adapters/outbound/langsmith.yaml
project: "my-service-dev"
endpoint: "https://api.smith.langchain.com"
api_key_env: LANGSMITH_API_KEY
workspace_id_env: LANGSMITH_WORKSPACE_ID

tracing:
  enabled: true
  mode: otel
  sampling_rate: 1.0

instrumentation:
  langgraph: true
  pydantic_ai: true
  fastapi: false
  fastmcp: true
  command_bus: true

capture:
  inputs: false
  outputs: false
  metadata: true
  model_content: false
  binary_content: false
  model_request_parameters: false

propagation:
  enabled: true
  langsmith_headers: true
  traceparent: true
  baggage_allowlist: []

tags:
  - arclith
metadata:
  deployment.environment: development

lifecycle:
  flush_timeout_seconds: 5.0

diagnostics:
  enabled: true
  log_level: info

failure_mode: log-and-continue
```

Les prompts, réponses, arguments/résultats de tools et contenus binaires sont masqués par défaut.
Activer leur capture uniquement après analyse des données et de leur durée de rétention.

Pour une redaction métier plus fine, le projet consommateur injecte une fonction neutre au
composition root. Arclith la transmet au client sans connaître les champs du domaine:

```python
from typing import Any

from arclith import Arclith


def redact_trace(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    sanitized.pop("email", None)
    return sanitized


arclith = Arclith("config", trace_anonymizer=redact_trace)
```

Cette fonction complète les interrupteurs `capture.*`; elle ne doit jamais réintroduire un champ
masqué ni journaliser le payload reçu.

## Profils CLI

`development` active un sampling à `1.0` et les diagnostics. `production` utilise `0.1`, désactive
les diagnostics et conserve tous les contenus sensibles masqués. Les deux profils gardent
`model_content: false`; une capture explicite reste nécessaire.

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --profile production \
  --param sampling_rate=0.05 \
  --yes
```

## Précédence

La résolution est déterministe:

1. contexte d'invocation;
2. variables `LANGSMITH_*`;
3. YAML;
4. valeurs sûres par défaut.

Overrides supportés: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`,
`LANGSMITH_WORKSPACE_ID`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`,
`LANGSMITH_TRACING_SAMPLING_RATE`, `LANGSMITH_HIDE_INPUTS`,
`LANGSMITH_HIDE_OUTPUTS`, `LANGSMITH_HIDE_METADATA` et `LANGSMITH_TRACING_MODE`.

Arclith ne transforme jamais le YAML en mutations de `os.environ`.

## API neutre

```python
tracer = arclith.tracer()

with tracer.span(
    "resolve-user-intent",
    kind="chain",
    metadata={"feature": "todo-agent"},
) as span:
    result = resolve_intent()
    span.set_outputs({"status": "resolved"})
```

Désactiver une invocation sensible sans modifier la configuration globale:

```python
with tracer.context(enabled=False):
    await process_sensitive_request()
```

Le contexte accepte aussi `project`, `tags`, `metadata` et `parent`. Seuls
`langsmith-trace`, `traceparent` et le baggage allowlisté peuvent être propagés.

## API LangSmith avancée

Arclith n'encapsule pas datasets, feedbacks, évaluations ou prompts:

```python
client = arclith.langsmith_client()
```

Le client est préconfiguré avec endpoint, workspace, politique de capture, mode et sampling. Il
permet d'utiliser directement les nouvelles fonctions du SDK LangSmith.

Pour un script court:

```python
try:
    run_job()
finally:
    arclith.flush_observability()
    arclith.close_observability()
```

FastAPI, FastMCP et les runners Arclith ferment automatiquement le runtime à l'arrêt.

## Instrumentation automatique

- `Arclith.langgraph()` configure le client, projet, tags et métadonnées avant compilation.
- `Arclith.pydantic_ai_llm()` injecte l'instrumentation uniquement dans les agents Pydantic AI
  construits par Arclith; aucun `Agent.instrument_all()` global n'est utilisé.
- `Arclith.instrument_mcp()` trace les tools sans capturer leurs arguments/résultats bruts.
- `Arclith.rabbitmq_command_bus()` injecte le contexte à la publication et l'extrait autour du
  handler.
- `instrumentation.fastapi: true` ajoute un span HTTP LangSmith lorsque FastAPI n'est pas déjà
  instrumenté par OpenTelemetry.

Les metadata de transport sont bornées: méthode/route HTTP, nom du tool, type de commande,
destination et statut. Les payloads métier ne sont jamais ajoutés automatiquement.

## LangSmith et OpenTelemetry ensemble

Les deux adapters partagent un seul `TracerProvider` et plusieurs processors/exporters. Lorsque les
deux sont activés, `tracing.mode` doit être `otel`; la configuration est refusée autrement pour
éviter deux arbres concurrents.

```yaml
observability:
  enabled:
    - opentelemetry
    - langsmith
```

L'instrumentation FastAPI et Pydantic AI n'est alors créée qu'une fois et les spans sont fan-out vers
OTLP et LangSmith. Une panne d'export reste fail-open et ne doit pas interrompre le métier.

## Hors ligne

Pour exécuter LangGraph sans LangSmith et sans clé, retirer `langsmith` de
`observability.enabled`. L'extra `langgraph` ne déclare plus directement LangSmith; une éventuelle
dépendance transitive du runtime LangGraph n'est jamais initialisée par Arclith.

```yaml
observability:
  enabled: []
```

Le graphe et `arclith.tracer()` continuent de fonctionner localement.

## Test live optionnel

Le test d'intégration est désactivé par défaut. Il émet un run identifiable, force le flush puis le
recherche via le client:

```bash
ARCLITH_LANGSMITH_INTEGRATION=1 \
LANGSMITH_API_KEY="<secret>" \
LANGSMITH_PROJECT="arclith-integration" \
uv run --extra all pytest -q tests/integration/test_langsmith.py
```

## Dépannage

- `clé API absente`: injecter `LANGSMITH_API_KEY` ou retirer l'adapter de
  `observability.enabled`.
- `trace absente`: vérifier successivement `observability.enabled`, `tracing.enabled`, le sampling,
  `LANGSMITH_TRACING` et le projet résolu dans `arclith.observability_diagnostics()`.
- `ancienne valeur encore utilisée`: les variables sont résolues au démarrage lazy du runtime et
  le client est ensuite conservé. Redémarrer le worker après un changement de secret ou de
  `LANGSMITH_*`; Arclith ne relit pas l'environnement pour chaque span.
- `spans dupliqués`: avec OpenTelemetry actif, imposer `tracing.mode: otel` et ne conserver qu'une
  instrumentation FastAPI.
- `Studio local hors ligne`: retirer LangSmith de l'activation et appeler directement l'API locale
  LangGraph.

## Suite

Lire [Observabilité production](../production/observability.md), [logger](logger.md),
[agent](agent.md) et [Validation IA locale](../learning/local-ai-validation.md).
