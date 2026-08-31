from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    FileTemplateSpec,
    ParameterSpec,
    SecretMappingSpec,
)

CACHE_CAPABILITY = CapabilitySpec(
    name="cache",
    layer="outbound",
    description="Cache transverse pour JWT JWKS, idempotency et résolution tenant.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="memory",
            capability="cache",
            layer="outbound",
            description="Cache local par processus pour dev, tests et exécution mono-worker.",
            config_path="config/adapters/inbound/cache.yaml",
            config_template="""\
backend: memory
jwks_ttl: {jwks_ttl}
tenant_uri_ttl: {tenant_uri_ttl}
""",
            parameters=(
                ParameterSpec(
                    name="jwks_ttl",
                    kind="string",
                    prompt="TTL JWKS en secondes",
                    default="3600",
                ),
                ParameterSpec(
                    name="tenant_uri_ttl",
                    kind="string",
                    prompt="TTL tenant en secondes",
                    default="300",
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="redis",
            capability="cache",
            layer="outbound",
            description="Cache Redis partagé pour déploiements multi-worker ou multi-réplicas.",
            config_path="config/adapters/inbound/cache.yaml",
            config_template="""\
backend: redis
redis_url: ""
jwks_ttl: {jwks_ttl}
tenant_uri_ttl: {tenant_uri_ttl}
""",
            env_path=".env",
            env_template="""\
REDIS_URL={redis_url}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="cache.redis_url",
                    secret_key="REDIS_URL",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="redis_url",
                    kind="string",
                    prompt="REDIS_URL",
                    default="redis://127.0.0.1:6379",
                    secret=True,
                ),
                ParameterSpec(
                    name="jwks_ttl",
                    kind="string",
                    prompt="TTL JWKS en secondes",
                    default="3600",
                ),
                ParameterSpec(
                    name="tenant_uri_ttl",
                    kind="string",
                    prompt="TTL tenant en secondes",
                    default="300",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

LOGGER_CAPABILITY = CapabilitySpec(
    name="logger",
    layer="outbound",
    description="Logger applicatif partagé par les use cases et adapters.",
    activation_config_key="logger",
    adapters=(
        AdapterSpec(
            name="console",
            capability="logger",
            layer="outbound",
            description="Logger console Loguru enrichi avec les métadonnées OpenTelemetry courantes.",
            entity_scoped=False,
        ),
    ),
)

SECRETS_CAPABILITY = CapabilitySpec(
    name="secrets",
    layer="outbound",
    description="Résolution de secrets avant validation de la configuration Arclith.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="env",
            capability="secrets",
            layer="outbound",
            description="Resolver de secrets depuis les variables d'environnement Docker, CI/CD ou Kubernetes.",
            secret_resolver="env",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="{field_path}",
                    secret_key="{secret_key}",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="field_path",
                    kind="string",
                    prompt="Champ de configuration à alimenter",
                    required=True,
                ),
                ParameterSpec(
                    name="secret_key",
                    kind="string",
                    prompt="Variable d'environnement explicite (vide = dérivée du champ)",
                    default="",
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="yaml",
            capability="secrets",
            layer="outbound",
            description="Resolver YAML local gitignoré pour POC et développement sans Vault.",
            secret_resolver="yaml",
            secret_config_template="""\
yaml:
  path: "{path}"
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="{field_path}",
                    secret_key="{secret_key}",
                ),
            ),
            file_templates=(
                FileTemplateSpec(
                    path="secrets.yaml.template",
                    template="""\
# Copiez ce fichier vers secrets.yaml pour le développement local.
# Ne commitez jamais secrets.yaml.
{secret_template_yaml}
""",
                ),
            ),
            gitignore_entries=("secrets.yaml",),
            parameters=(
                ParameterSpec(
                    name="field_path",
                    kind="string",
                    prompt="Champ de configuration à alimenter",
                    required=True,
                ),
                ParameterSpec(
                    name="secret_key",
                    kind="string",
                    prompt="Clé descriptive du secret (ignorée par le resolver YAML)",
                    default="",
                ),
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="Chemin du fichier YAML local",
                    default="secrets.yaml",
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="vault",
            capability="secrets",
            layer="outbound",
            description="Resolver HashiCorp Vault KV v2 pour secrets applicatifs.",
            secret_resolver="vault",
            secret_config_template="""\
vault:
  addr: "{addr}"
  mount: "{mount}"
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="{field_path}",
                    secret_key="{secret_key}",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="field_path",
                    kind="string",
                    prompt="Champ de configuration à alimenter",
                    required=True,
                ),
                ParameterSpec(
                    name="secret_key",
                    kind="string",
                    prompt="Chemin Vault relatif au mount KV v2",
                    required=True,
                ),
                ParameterSpec(
                    name="addr",
                    kind="string",
                    prompt="Adresse Vault",
                    default="http://127.0.0.1:8200",
                ),
                ParameterSpec(
                    name="mount",
                    kind="string",
                    prompt="Mount KV v2",
                    default="kv",
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="chain",
            capability="secrets",
            layer="outbound",
            description="Resolver ordonné avec fallback entre env, Vault et YAML.",
            secret_resolver="chain",
            secret_config_template="""\
chain:
{secret_chain_yaml}
vault:
  addr: "{addr}"
  mount: "{mount}"
yaml:
  path: "{path}"
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="{field_path}",
                    secret_key="{secret_key}",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="field_path",
                    kind="string",
                    prompt="Champ de configuration à alimenter",
                    required=True,
                ),
                ParameterSpec(
                    name="secret_key",
                    kind="string",
                    prompt="Chemin Vault relatif au mount ou clé explicite",
                    required=True,
                ),
                ParameterSpec(
                    name="resolvers",
                    kind="string",
                    prompt="Resolvers ordonnés séparés par virgule",
                    default="env,vault,yaml",
                    choices=("env", "vault", "yaml"),
                    csv_choices=True,
                ),
                ParameterSpec(
                    name="addr",
                    kind="string",
                    prompt="Adresse Vault",
                    default="http://127.0.0.1:8200",
                ),
                ParameterSpec(
                    name="mount",
                    kind="string",
                    prompt="Mount KV v2",
                    default="kv",
                ),
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="Chemin du fichier YAML local",
                    default="secrets.yaml",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)
