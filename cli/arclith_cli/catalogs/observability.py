from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterProfileSpec,
    AdapterSpec,
    CapabilitySpec,
    ParameterSpec,
)

OBSERVABILITY_CAPABILITY = CapabilitySpec(
    name="observability",
    layer="outbound",
    description="Observabilité activable en parallèle via LangSmith et OpenTelemetry.",
    activation_config_key="observability",
    adapters=(
        AdapterSpec(
            name="langsmith",
            capability="observability",
            layer="outbound",
            description="Tracing LangSmith et tests agent dans LangGraph Studio.",
            config_path="config/adapters/outbound/langsmith.yaml",
            config_template="""\
project: "{project}"
endpoint: "{endpoint}"
api_key_env: LANGSMITH_API_KEY
workspace_id_env: LANGSMITH_WORKSPACE_ID
# Définir LANGSMITH_API_KEY hors Git: .env local, env runtime ou secret manager.
tracing:
  enabled: {tracing_enabled}
  mode: "{tracing_mode}"
  sampling_rate: {sampling_rate}
instrumentation:
  langgraph: {instrument_langgraph}
  pydantic_ai: {instrument_pydantic_ai}
  fastapi: {instrument_fastapi}
  fastmcp: {instrument_fastmcp}
  command_bus: {instrument_command_bus}
capture:
  inputs: {capture_inputs}
  outputs: {capture_outputs}
  metadata: {capture_metadata}
  model_content: {capture_model_content}
  binary_content: false
  model_request_parameters: false
propagation:
  enabled: true
  langsmith_headers: true
  traceparent: true
  baggage_allowlist: []
tags:
  - arclith
metadata: {{}}
lifecycle:
  flush_timeout_seconds: 5.0
diagnostics:
  enabled: {diagnostics_enabled}
  log_level: info
failure_mode: log-and-continue
studio: langgraph
langgraph_api_min_version: "0.11.0"
""",
            env_path=".env.example",
            env_template="""\
LANGSMITH_TRACING={tracing_enabled}
LANGSMITH_PROJECT={project}
LANGSMITH_ENDPOINT={endpoint}
LANGSMITH_TRACING_MODE={tracing_mode}
LANGSMITH_TRACING_SAMPLING_RATE={sampling_rate}
LANGSMITH_HIDE_INPUTS={hide_inputs}
LANGSMITH_HIDE_OUTPUTS={hide_outputs}
LANGSMITH_HIDE_METADATA={hide_metadata}
""",
            parameters=(
                ParameterSpec(
                    name="tracing_enabled",
                    kind="boolean",
                    prompt="Activer le tracing LangSmith",
                    default=True,
                ),
                ParameterSpec(
                    name="project",
                    kind="string",
                    prompt="Projet LangSmith",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="endpoint",
                    kind="string",
                    prompt="Endpoint LangSmith",
                    default="https://api.smith.langchain.com",
                ),
                ParameterSpec(
                    name="tracing_mode",
                    kind="string",
                    prompt="Mode de tracing LangSmith",
                    default="otel",
                    choices=("langsmith", "otel", "hybrid"),
                ),
                ParameterSpec(
                    name="sampling_rate",
                    kind="string",
                    prompt="Taux d'échantillonnage (0.0-1.0)",
                    default="1.0",
                ),
                ParameterSpec(
                    name="capture_inputs",
                    kind="boolean",
                    prompt="Capturer les inputs",
                    default=False,
                ),
                ParameterSpec(
                    name="capture_outputs",
                    kind="boolean",
                    prompt="Capturer les outputs",
                    default=False,
                ),
                ParameterSpec(
                    name="capture_metadata",
                    kind="boolean",
                    prompt="Capturer les métadonnées",
                    default=True,
                ),
                ParameterSpec(
                    name="capture_model_content",
                    kind="boolean",
                    prompt="Capturer prompts et réponses modèle (sensible)",
                    default=False,
                ),
                ParameterSpec(
                    name="instrument_langgraph",
                    kind="boolean",
                    prompt="Instrumenter LangGraph",
                    default=True,
                ),
                ParameterSpec(
                    name="instrument_pydantic_ai",
                    kind="boolean",
                    prompt="Instrumenter Pydantic AI",
                    default=True,
                ),
                ParameterSpec(
                    name="instrument_fastapi",
                    kind="boolean",
                    prompt="Instrumenter FastAPI",
                    default=False,
                ),
                ParameterSpec(
                    name="instrument_fastmcp",
                    kind="boolean",
                    prompt="Instrumenter FastMCP",
                    default=True,
                ),
                ParameterSpec(
                    name="instrument_command_bus",
                    kind="boolean",
                    prompt="Instrumenter le command bus",
                    default=True,
                ),
                ParameterSpec(
                    name="diagnostics_enabled",
                    kind="boolean",
                    prompt="Activer les diagnostics locaux",
                    default=False,
                ),
            ),
            profiles=(
                AdapterProfileSpec(
                    name="development",
                    parameters=(
                        ("tracing_enabled", True),
                        ("tracing_mode", "otel"),
                        ("sampling_rate", "1.0"),
                        ("capture_inputs", False),
                        ("capture_outputs", False),
                        ("capture_model_content", False),
                        ("diagnostics_enabled", True),
                    ),
                ),
                AdapterProfileSpec(
                    name="production",
                    parameters=(
                        ("tracing_enabled", True),
                        ("tracing_mode", "otel"),
                        ("sampling_rate", "0.1"),
                        ("capture_inputs", False),
                        ("capture_outputs", False),
                        ("capture_model_content", False),
                        ("diagnostics_enabled", False),
                    ),
                ),
            ),
            dependency_extra="langsmith",
            gitignore_entries=(".env",),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="opentelemetry",
            capability="observability",
            layer="outbound",
            description="Runtime OTLP traces, métriques, logs et propagation W3C.",
            config_path="config/adapters/outbound/opentelemetry.yaml",
            config_template="""\
mode: "{mode}"
service:
  name: "{service_name}"
  namespace: null
  version: null
  instance_id_env: OTEL_SERVICE_INSTANCE_ID
resource:
  attributes:
    deployment.environment.name: "{deployment_environment}"
  detectors: [env, process, host]
export:
  protocol: "{protocol}"
  endpoint: "{endpoint}"
  traces_endpoint: null
  metrics_endpoint: null
  logs_endpoint: null
  headers_env: OTEL_EXPORTER_OTLP_HEADERS
  compression: gzip
  timeout_millis: 10000
  insecure: false
signals:
  traces:
    enabled: {traces}
    sampler: parentbased_traceidratio
    sampling_ratio: {sampling_ratio}
  metrics:
    enabled: {metrics}
    export_interval_millis: {metrics_export_interval_millis}
    export_timeout_millis: 30000
    exemplar_filter: trace_based
  logs:
    enabled: {logs}
    correlate: {correlate_logs}
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
failure_mode: log-and-continue
""",
            env_path=".env.example",
            env_template="""\
OTEL_SERVICE_NAME={service_name}
OTEL_EXPORTER_OTLP_ENDPOINT={endpoint}
OTEL_EXPORTER_OTLP_PROTOCOL={protocol}
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG={sampling_ratio}
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name={deployment_environment}
# OTEL_EXPORTER_OTLP_HEADERS vient du secret store du runtime, jamais de Git.
""",
            parameters=(
                ParameterSpec(
                    name="service_name",
                    kind="string",
                    prompt="OTEL_SERVICE_NAME",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="endpoint",
                    kind="string",
                    prompt="OTLP endpoint",
                    default="http://localhost:4318",
                ),
                ParameterSpec(
                    name="mode",
                    kind="string",
                    prompt="Mode de composition des providers",
                    default="managed",
                    choices=("managed", "attach", "external"),
                ),
                ParameterSpec(
                    name="protocol",
                    kind="string",
                    prompt="OTLP protocol",
                    default="http/protobuf",
                    choices=("http/protobuf", "grpc"),
                ),
                ParameterSpec(
                    name="traces",
                    kind="boolean",
                    prompt="Exporter les traces",
                    default=True,
                ),
                ParameterSpec(
                    name="metrics",
                    kind="boolean",
                    prompt="Exporter les métriques",
                    default=False,
                ),
                ParameterSpec(
                    name="logs",
                    kind="boolean",
                    prompt="Exporter les logs OTLP",
                    default=False,
                ),
                ParameterSpec(
                    name="correlate_logs",
                    kind="boolean",
                    prompt="Corréler les logs locaux",
                    default=True,
                ),
                ParameterSpec(
                    name="sampling_ratio",
                    kind="string",
                    prompt="Taux d'échantillonnage traces (0.0-1.0)",
                    default="1.0",
                ),
                ParameterSpec(
                    name="metrics_export_interval_millis",
                    kind="string",
                    prompt="Intervalle export métriques en ms",
                    default="60000",
                ),
                ParameterSpec(
                    name="deployment_environment",
                    kind="string",
                    prompt="Environnement de déploiement",
                    default="development",
                    choices=("development", "test", "staging", "production"),
                ),
            ),
            profiles=(
                AdapterProfileSpec(
                    name="development",
                    parameters=(
                        ("mode", "managed"),
                        ("traces", True),
                        ("metrics", True),
                        ("logs", False),
                        ("correlate_logs", True),
                        ("sampling_ratio", "1.0"),
                        ("deployment_environment", "development"),
                    ),
                ),
                AdapterProfileSpec(
                    name="production",
                    parameters=(
                        ("mode", "managed"),
                        ("traces", True),
                        ("metrics", True),
                        ("logs", False),
                        ("correlate_logs", True),
                        ("sampling_ratio", "0.1"),
                        ("deployment_environment", "production"),
                    ),
                ),
            ),
            dependency_extra="opentelemetry",
            gitignore_entries=(".env",),
            entity_scoped=False,
        ),
    ),
)
