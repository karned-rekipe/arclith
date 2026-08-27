# Observabilité Production

L'observabilité Arclith reste un adapter outbound optionnel. Le domaine et les use cases ne
connaissent ni LangSmith ni OpenTelemetry.

## Stack cible

| Besoin | Choix |
|---|---|
| Traces runtime/API | OpenTelemetry |
| Traces agent et GenAI | LangSmith via le provider OpenTelemetry partagé |
| Logs | logger structuré avec corrélation |
| Santé | probes HTTP |
| Propagation | W3C `traceparent` et `langsmith-trace` |

## Générer le profil production

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter opentelemetry \
  --yes

arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --profile production \
  --yes
```

Lorsque les deux backends sont actifs, LangSmith doit utiliser `tracing.mode: otel`. Arclith refuse
les modes natif/hybride dans cette combinaison afin d'éviter les doublons.

## Secrets et variables

```bash
export OTEL_SERVICE_NAME=my-service
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production
export LANGSMITH_API_KEY="<secret>"
export LANGSMITH_PROJECT=my-service-production
export LANGSMITH_TRACING=true
export LANGSMITH_TRACING_MODE=otel
export LANGSMITH_TRACING_SAMPLING_RATE=0.05
export LANGSMITH_HIDE_INPUTS=true
export LANGSMITH_HIDE_OUTPUTS=true
export LANGSMITH_HIDE_METADATA=false
```

Une clé appartenant à plusieurs workspaces requiert aussi `LANGSMITH_WORKSPACE_ID`.

Ne jamais mettre la clé dans le YAML, `.env.example`, un argument CLI, une image ou un manifeste
versionné. Utiliser le secret store de la plateforme.

## Politique recommandée

- prompts, réponses, tools, binaires et paramètres modèle masqués;
- sampling adapté au volume;
- baggage vide ou allowlisté clé par clé;
- aucune donnée tenant brute; utiliser un hash stable seulement si nécessaire;
- diagnostics LangSmith désactivés hors incident;
- timeouts et buffers bornés;
- Collector OTLP recommandé pour le fan-out runtime;
- `failure_mode: log-and-continue` pour ne jamais bloquer le métier.

Les metadata stables recommandées sont `service.name`, `service.version`,
`deployment.environment`, `release.revision`, `request.id`, `correlation.id`, `thread_id` et un
éventuel `tenant.id_hash` non réversible.

## Cycle de vie

FastAPI, FastMCP et le command bus démarrent le runtime après fork et appellent flush/close à
l'arrêt. Les scripts et workers personnalisés doivent utiliser:

```python
try:
    run_worker()
finally:
    arclith.close_observability(timeout=5.0)
```

La panne du Collector ou de LangSmith ne rend pas le service indisponible. Une dépendance absente,
une configuration incohérente ou une clé manquante lorsque LangSmith est activé provoque en revanche
une erreur de démarrage actionnable.

## Vérifier

```bash
uv run --extra all pytest
curl -fsS http://127.0.0.1:9000/health
```

Vérifier aussi qu'une requête API, un tool MCP, une commande RabbitMQ et un run agent partagent le
même contexte, sans payload sensible ni span dupliqué.

## Suite

Lire [runtime et probes](runtime.md), [capability observability](../capabilities/observability.md) et
[logger](../capabilities/logger.md).
