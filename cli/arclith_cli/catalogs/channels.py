from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    ParameterSpec,
    SecretMappingSpec,
)

CHANNEL_CAPABILITY = CapabilitySpec(
    name="channel",
    layer="bidirectional",
    description="Messages conversationnels entrants et sortants normalisés.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="memory",
            capability="channel",
            layer="bidirectional",
            description="Fake déterministe en mémoire pour tests et prototypes locaux.",
            config_path="config/adapters/bidirectional/memory.yaml",
            config_template="""\
enabled: true
""",
            entity_scoped=False,
        ),
        AdapterSpec(
            name="webhook",
            capability="channel",
            layer="bidirectional",
            description="Webhook HTTP générique signé, idempotent et provider-neutral.",
            config_path="config/adapters/bidirectional/webhook.yaml",
            config_template="""\
enabled: true
path: "{path}"
secret: null
signature_header: "{signature_header}"
timestamp_header: "{timestamp_header}"
signature_tolerance_seconds: {signature_tolerance_seconds}
idempotency_header: "{idempotency_header}"
event_ttl_seconds: {event_ttl_seconds}
max_payload_bytes: {max_payload_bytes}
metadata_allowlist: []
response_mode: "{response_mode}"
callback_url: {callback_url}
callback_allowed_host: {callback_allowed_host}
callback_timeout_seconds: {callback_timeout_seconds}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.channel.webhook.secret",
                    secret_key="ARCLITH_WEBHOOK_SECRET",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="Route HTTP statique du webhook",
                    default="/channels/webhook",
                ),
                ParameterSpec(
                    name="signature_header",
                    kind="string",
                    prompt="Header de signature HMAC",
                    default="X-Arclith-Signature",
                ),
                ParameterSpec(
                    name="timestamp_header",
                    kind="string",
                    prompt="Header du timestamp signé",
                    default="X-Arclith-Timestamp",
                ),
                ParameterSpec(
                    name="signature_tolerance_seconds",
                    kind="string",
                    prompt="Tolérance de fraîcheur HMAC en secondes",
                    default="300",
                ),
                ParameterSpec(
                    name="idempotency_header",
                    kind="string",
                    prompt="Header de l'identifiant stable de l'événement",
                    default="X-Arclith-Event-Id",
                ),
                ParameterSpec(
                    name="event_ttl_seconds",
                    kind="string",
                    prompt="Durée de déduplication en secondes",
                    default="86400",
                ),
                ParameterSpec(
                    name="max_payload_bytes",
                    kind="string",
                    prompt="Taille maximale du payload en octets",
                    default="1048576",
                ),
                ParameterSpec(
                    name="response_mode",
                    kind="string",
                    prompt="Mode de réponse HTTP",
                    default="sync",
                    choices=("sync", "accepted", "callback"),
                ),
                ParameterSpec(
                    name="callback_url",
                    kind="string",
                    prompt="URL HTTPS du callback côté serveur (null hors mode callback)",
                    default="null",
                ),
                ParameterSpec(
                    name="callback_allowed_host",
                    kind="string",
                    prompt="Hostname exact autorisé pour le callback (null hors mode callback)",
                    default="null",
                ),
                ParameterSpec(
                    name="callback_timeout_seconds",
                    kind="string",
                    prompt="Timeout du callback sortant en secondes",
                    default="5.0",
                ),
            ),
            dependency_extra="channel",
            entity_scoped=False,
        ),
        AdapterSpec(
            name="slack",
            capability="channel",
            layer="bidirectional",
            description="Slack Events API signé avec réponses chat.postMessage.",
            config_path="config/adapters/bidirectional/slack.yaml",
            config_template="""\
enabled: true
path: "{path}"
signing_secret: null
bot_token: null
workspace_id: {workspace_id}
allowed_channel_ids: []
signature_tolerance_seconds: {signature_tolerance_seconds}
event_ttl_seconds: {event_ttl_seconds}
max_payload_bytes: {max_payload_bytes}
request_timeout_seconds: {request_timeout_seconds}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.channel.slack.signing_secret",
                    secret_key="ARCLITH_SLACK_SIGNING_SECRET",
                ),
                SecretMappingSpec(
                    field_path="adapters.channel.slack.bot_token",
                    secret_key="ARCLITH_SLACK_BOT_TOKEN",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="Route HTTP statique des événements Slack",
                    default="/channels/slack/events",
                ),
                ParameterSpec(
                    name="workspace_id",
                    kind="string",
                    prompt="Workspace Slack exact autorisé (null pour tout accepter)",
                    default="null",
                ),
                ParameterSpec(
                    name="signature_tolerance_seconds",
                    kind="string",
                    prompt="Tolérance de fraîcheur de signature en secondes",
                    default="300",
                ),
                ParameterSpec(
                    name="event_ttl_seconds",
                    kind="string",
                    prompt="Durée de déduplication des event_id en secondes",
                    default="86400",
                ),
                ParameterSpec(
                    name="max_payload_bytes",
                    kind="string",
                    prompt="Taille maximale du payload en octets",
                    default="1048576",
                ),
                ParameterSpec(
                    name="request_timeout_seconds",
                    kind="string",
                    prompt="Timeout de chat.postMessage en secondes",
                    default="5.0",
                ),
            ),
            dependency_extra="channel",
            entity_scoped=False,
        ),
    ),
)

__all__ = ["CHANNEL_CAPABILITY"]
