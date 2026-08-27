# OpenTelemetry de bout en bout

Arclith fournit un runtime OpenTelemetry optionnel qui compose les providers, les exporters OTLP,
la propagation et les instrumentations aux frontières. Le domaine et les use cases ne dépendent que
des ports neutres `TracePort`, `MetricPort`, `CorrelationContextPort`,
`ContextPropagatorPort` et `ObservabilityRuntimePort`.

Les projets consommateurs restent responsables de leurs attributs métier, dashboards, alertes,
règles de rétention et budgets de télémétrie.

## Les trois opt-in

OpenTelemetry n'est actif que si les trois décisions suivantes sont prises séparément :

1. installer l'extra `arclith[opentelemetry]` ;
2. ajouter `opentelemetry` à `adapters.observability.enabled` ;
3. activer au moins un signal dans `signals.traces`, `signals.metrics` ou `signals.logs`.

Sans activation, Arclith utilise `NoOpObservabilityRuntime`. Aucun SDK, provider, processor,
thread, exporter ou appel réseau OpenTelemetry n'est créé. La corrélation et la propagation restent
accessibles derrière des no-op.

## Générer un profil

Profil local :

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter opentelemetry \
  --profile development \
  --yes
```

Le profil `development` active traces et métriques, sampling à 100 %, corrélation locale des logs
et endpoint Collector local. L'export OTLP des logs et toute capture de contenu restent désactivés.

Profil production :

```bash
arclith-cli add-adapter \
  --capability observability \
  --adapter opentelemetry \
  --profile production \
  --param sampling_ratio=0.05 \
  --yes
```

Le profil `production` utilise un sampler parent-based, active traces et métriques, conserve les
logs OTLP en opt-in et n'écrit aucun header d'authentification dans Git. Le CLI ajoute l'extra
Python et fusionne `.env.example` de façon idempotente.

## Configuration complète

```yaml
# config/adapters/adapters.yaml
observability:
  enabled:
    - opentelemetry
```

```yaml
# config/adapters/outbound/opentelemetry.yaml
mode: managed

service:
  name: null                       # fallback sur app.name
  namespace: rekipe
  version: null                    # fallback sur app.version
  instance_id_env: OTEL_SERVICE_INSTANCE_ID

resource:
  attributes:
    deployment.environment.name: production
  detectors: [env, process, host]

export:
  protocol: http/protobuf          # http/protobuf | grpc
  endpoint: http://otel-collector:4318
  traces_endpoint: null
  metrics_endpoint: null
  logs_endpoint: null
  headers_env: OTEL_EXPORTER_OTLP_HEADERS
  compression: gzip
  timeout_millis: 10000
  insecure: false

signals:
  traces:
    enabled: true
    sampler: parentbased_traceidratio
    sampling_ratio: 0.10
  metrics:
    enabled: true
    export_interval_millis: 60000
    export_timeout_millis: 30000
    exemplar_filter: trace_based
  logs:
    enabled: false                 # export OTLP
    correlate: true                # trace_id/span_id dans les logs locaux

propagation:
  propagators: [tracecontext, baggage]
  baggage_allowlist: []
  max_baggage_bytes: 8192

instrumentation:
  fastapi: true
  httpx: true
  fastmcp: true
  rabbitmq: true
  pydantic_ai: true
  langgraph: true
  repositories: false
  caches: false
  excluded_urls: [/health, /ready, /metrics]

capture:
  request_headers_allowlist: []
  response_headers_allowlist: []
  genai_content: false
  tool_content: false
  db_statement: false

batch:
  max_queue_size: 2048
  schedule_delay_millis: 5000
  max_export_batch_size: 512
  export_timeout_millis: 30000

limits:
  attribute_count: 128
  attribute_value_length: 4096
  span_event_count: 128
  span_link_count: 128

flush_timeout_seconds: 5.0
failure_mode: log-and-continue
```

L'ancien YAML plat (`service_name`, `endpoint`, `traces`, `metrics`,
`instrument_fastapi`, etc.) reste accepté et migré en mémoire. Les nouveaux projets doivent
utiliser la forme imbriquée.

## Précédence et variables standard

La résolution suit :

1. `opentelemetry_overrides` passé à `Arclith` ;
2. variables `OTEL_*` ;
3. YAML ;
4. valeurs par défaut.

```python
arclith = Arclith(
    "config",
    opentelemetry_overrides={
        "signals": {"traces": {"sampling_ratio": 1.0}},
    },
)
```

Arclith supporte notamment `OTEL_SDK_DISABLED`, `OTEL_SERVICE_NAME`,
`OTEL_RESOURCE_ATTRIBUTES`, `OTEL_EXPORTER_OTLP_*`, les endpoints et headers propres à chaque
signal, `OTEL_TRACES_EXPORTER`, `OTEL_METRICS_EXPORTER`, `OTEL_LOGS_EXPORTER`,
`OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG`, `OTEL_PROPAGATORS`, les réglages batch et les
limites d'attributs/spans.

Les variables ne sont jamais recopiées dans `os.environ`. Une valeur vide est traitée comme
absente. Les booléens standard acceptent uniquement `true` ou `false`, insensibles à la casse.

Les headers restent dans le secret store :

```bash
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20<secret>"
```

Ne jamais placer cette valeur dans YAML, `.env.example`, une image ou un manifeste versionné.
Les diagnostics exposent seulement le nom `headers_env`, jamais sa valeur.

## Identité de service et ressources

`service.name` est toujours résolu : `OTEL_SERVICE_NAME`, puis `service.name`, puis `app.name`.
`service.version` retombe sur `app.version`. `service.namespace` groupe plusieurs services et
`service.instance.id` peut provenir de la variable configurée par `instance_id_env`.

`OTEL_RESOURCE_ATTRIBUTES` surcharge les attributs YAML. Les détecteurs `process` et `host`
ajoutent uniquement des attributs techniques standards. Arclith ne déclare aucun
`telemetry.distro.*` et ne se présente donc pas comme une distribution OpenTelemetry officielle.

## Modes de providers

| Mode | Responsabilité Arclith | Provider existant | Shutdown |
|---|---|---|---|
| `managed` | crée providers, readers, processors et exporters | refusé s'il n'est pas un proxy | ferme les ressources au dernier runtime |
| `attach` | ajoute les processors traces/logs compatibles | obligatoire | ferme uniquement les processors ajoutés |
| `external` | n'ajoute aucun exporter | obligatoire | ne flush ni ne ferme le provider externe |

En mode `attach`, Python ne permet pas d'ajouter publiquement un metric reader à un
`MeterProvider` déjà construit. Son propriétaire doit donc configurer l'export des métriques ;
Arclith utilise ce provider sans le remplacer.

Deux instances `Arclith` simultanées avec une configuration `managed` identique partagent les
providers sans dupliquer processors, handlers ou exporters. Une configuration différente dans le
même processus échoue avec un diagnostic explicite. Lorsque le dernier runtime managed est fermé,
les providers globaux Python ne peuvent pas être remplacés proprement : le processus doit être
redémarré avant de créer un nouveau runtime managed.

## Cycle de vie

FastAPI, les runners MCP et le command bus appellent `start()`, `force_flush()` et `shutdown()` aux
frontières appropriées. Les méthodes sont idempotentes et seules les ressources possédées par
Arclith sont fermées.

Pour un script personnalisé :

```python
try:
    run_job()
finally:
    arclith.flush_observability(timeout=5.0)
    arclith.close_observability(timeout=5.0)
```

Les batch queues et timeouts sont bornés. Une indisponibilité temporaire du Collector reste
fail-open ; une configuration invalide, une dépendance absente ou un conflit de provider échoue au
démarrage.

## Signaux et instrumentations

### Traces et propagation

`TracePort` crée des spans provider-neutral et enregistre les exceptions/statuts. La propagation
utilise une instance locale des propagateurs W3C, sans modifier le propagateur global. Les carriers
ne conservent que `traceparent`, `tracestate` et le baggage explicitement allowlisté et borné.

### FastAPI et HTTPX

FastAPI utilise l'instrumentation officielle avec providers explicites, routes bruyantes exclues et
spans ASGI internes `receive`/`send` supprimés. Les headers ne sont capturés que par allowlist ;
authorization, cookies et proxy authorization sont toujours sanitizés.

HTTPX est instrumenté uniquement si `instrumentation.httpx` et les traces sont actives. Le runtime
désinstrumente le client au dernier shutdown et évite les doubles monkey-patches. Pour les deux
instrumentations, Arclith remplace les attributs d'URL par une version sans query string ni
fragment, quel que soit le nom du paramètre.

### FastMCP

Les conventions MCP ne sont pas encore stabilisées. Arclith utilise donc des attributs isolés et
versionnés `arclith.mcp.*`, un span serveur `arclith.mcp.tool` et des métriques bornées. Arguments,
résultats et payloads ne sont pas capturés. Une future convention officielle pourra remplacer cet
adaptateur sans modifier le core.

### RabbitMQ

Le publisher crée un span producer et injecte `traceparent`, `tracestate` et le baggage autorisé.
Le consumer extrait et attache le contexte avant le handler, puis le détache dans un `finally`.
Les spans et métriques couvrent publication, traitement, succès, erreurs et rejet sans exporter le
payload de commande.

### Pydantic AI et LangGraph

Arclith injecte l'instrumentation Pydantic AI dans les seuls agents construits par
`pydantic_ai_llm()` ; aucun `Agent.instrument_all()` global n'est appelé. Les providers du runtime
sont transmis explicitement. `capture.genai_content` reste `false` par défaut car prompts,
réponses, messages et résultats de tools peuvent contenir secrets, PII et données métier.

Pour LangGraph, Arclith conserve l'objet `CompiledStateGraph` et observe en place ses frontières
`invoke`, `ainvoke`, `stream` et `astream`. Un seul span workflow englobe l'exécution, y compris
lorsque LangGraph délègue en interne d'une méthode à une autre ; ni l'état, ni les événements, ni le
résultat ne sont ajoutés aux spans.

### Repositories et caches

`instrumentation.repositories` et `instrumentation.caches` ajoutent des wrappers opt-in. Ils
mesurent opérations, durée, erreurs et hit/miss sans exporter entités, UUID, clés ou valeurs. Les
métriques locales des probes restent indépendantes ; Arclith n'installe pas un second middleware
HTTP de métriques lorsqu'un événement est déjà produit par l'instrumentation officielle.

## Logs : corrélation et export indépendants

`signals.logs.correlate` enrichit les logs locaux avec `trace_id`, `span_id` et le sampling flag.
`signals.logs.enabled` exporte en plus des records OTLP via batch processor.

Le logger Loguru existant reste la sortie console. Arclith émet les records OTLP explicitement via
un handler dédié et ne modifie pas le root logger, ce qui évite les doubles émissions et les boucles
avec les logs internes de l'exporter. Les logs OpenTelemetry Python restent un signal en évolution :
garder l'export en opt-in et valider le backend avant production.

## Confidentialité et cardinalité

Par défaut, Arclith ne capture pas :

- prompts, réponses LLM, arguments/résultats de tools ou contenu MCP ;
- corps HTTP, query string brute ou headers hors allowlist ;
- requête SQL, document de repository, entité, UUID ou clé de cache ;
- token, cookie, secret, payload ou baggage arbitraire.

Les labels de métriques rejettent les clés sensibles/identifiantes, les UUID, les textes longs et
les valeurs non scalaires. Utiliser des templates de routes, noms d'opérations et statuts bornés.
Une capture de contenu explicite implique une revue sécurité, une rétention limitée et un budget de
volume.

## OpenTelemetry et LangSmith

Les deux adapters peuvent être activés ensemble :

```yaml
observability:
  enabled: [opentelemetry, langsmith]
```

Dans ce cas, LangSmith doit utiliser `tracing.mode: otel`. Le runtime OpenTelemetry possède l'arbre
de spans et LangSmith ajoute un processor au même `TracerProvider`. FastAPI, Pydantic AI, LangGraph,
MCP et RabbitMQ ne sont instrumentés qu'une fois. Le shutdown ferme d'abord le processor LangSmith,
puis les providers possédés par OpenTelemetry.

Pour envoyer uniquement OpenTelemetry vers LangSmith, configurer le Collector ou l'endpoint OTLP
du tenant LangSmith et ne pas activer l'adapter LangSmith natif. Pour un mode hybride, conserver une
seule politique de sampling et de capture.

## API et diagnostics

```python
tracer = arclith.tracer()
metrics = arclith.metrics()

with tracer.span("application.boundary") as span:
    metrics.add_counter("application.operations", attributes={"operation": "sync"})
    span.set_outputs({"status": "success"})

print(arclith.observability_diagnostics())
```

Les diagnostics n'exposent jamais les headers OTLP ; ils retirent aussi credentials, query string
et fragment de l'endpoint avant affichage.

L'escape hatch vendor-specific est explicite :

```python
providers = arclith.observability_providers()
tracer_provider = providers.get("tracer_provider")
```

Ne faites pas remonter ces types dans le domaine ou les use cases.

## Collector local

Créer `collector-config.yaml` :

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
exporters:
  debug:
    verbosity: detailed
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
    metrics:
      receivers: [otlp]
      exporters: [debug]
    logs:
      receivers: [otlp]
      exporters: [debug]
```

Lancer le Collector :

```bash
docker run --rm \
  -p 4317:4317 -p 4318:4318 \
  -v "$PWD/collector-config.yaml:/etc/otelcol/config.yaml:ro" \
  otel/opentelemetry-collector:latest
```

Puis démarrer le service avec le profil development et appeler une route, un tool ou un worker.
Le terminal du Collector doit afficher les signaux sans corps, secrets ni contenus GenAI.

Le tag `latest` est pratique pour ce POC seulement. Épingler une version/digest dans tout runtime
partagé ou CI.

## Dépannage

- `extra absent` : installer `arclith[opentelemetry]` ou retirer l'adapter de l'activation.
- `provider existe déjà` : choisir `attach` si Arclith doit ajouter traces/logs, ou `external` si
  l'autre bootstrap possède toute la configuration.
- `aucune trace` : vérifier `observability.enabled`, `signals.traces.enabled`,
  `OTEL_SDK_DISABLED`, `OTEL_TRACES_EXPORTER`, sampling et exclusions.
- `aucune métrique en attach` : configurer le metric reader sur le provider externe.
- `spans dupliqués` : retirer l'auto-instrumentation globale et conserver une seule instrumentation
  Arclith ; avec LangSmith, imposer `tracing.mode: otel`.
- `headers absents` : vérifier l'allowlist et ne pas utiliser une query string comme label.
- `Collector indisponible` : les batch exporters journalisent une erreur bornée sans interrompre le
  métier ; vérifier endpoint, protocole, TLS, secret et timeout.

## Références

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [Exporters Python](https://opentelemetry.io/docs/languages/python/exporters/)
- [Variables d'environnement SDK](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)
- [Conventions de ressource](https://opentelemetry.io/docs/specs/semconv/resource/)
- [Conventions de service](https://opentelemetry.io/docs/specs/semconv/resource/service/)

Lire aussi [Observability](observability.md),
[Observabilité production](../production/observability.md) et
[Quickstart API](../quickstarts/api.md).
