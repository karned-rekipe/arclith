from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .runtime_templates import (
    ARCLITH_RUN_TEMPLATE,
    DEFAULT_AGENT_PORT,
    DEFAULT_API_PORT,
    DEFAULT_MCP_PORT,
    DEFAULT_PROBE_PORT,
    DEFAULT_UV_VERSION,
    DOCKERFILE_TEMPLATE,
    DOCKERIGNORE_TEMPLATE,
)

ParameterKind = Literal["string", "boolean"]
LayerKind = Literal["inbound", "outbound", "bidirectional", "runtime"]


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    prompt: str
    default: str | bool | None = None
    default_from_project_name: bool = False
    secret: bool = False
    required: bool = False
    choices: tuple[str, ...] = ()
    csv_choices: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "prompt": self.prompt,
            "default": self.default,
            "default_from_project_name": self.default_from_project_name,
            "secret": self.secret,
            "required": self.required,
            "choices": list(self.choices),
            "csv_choices": self.csv_choices,
        }


@dataclass(frozen=True)
class FileTemplateSpec:
    path: str
    template: str
    preserve_existing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "preserve_existing": self.preserve_existing,
        }


@dataclass(frozen=True)
class SecretMappingSpec:
    field_path: str
    secret_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "secret_key": self.secret_key,
        }


@dataclass(frozen=True)
class AdapterProfileSpec:
    name: str
    parameters: tuple[tuple[str, str | bool], ...]

    def values(self) -> dict[str, str | bool]:
        return dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    capability: str
    layer: LayerKind
    description: str
    config_path: str | None = None
    config_template: str = ""
    merge_config_templates: tuple[FileTemplateSpec, ...] = ()
    env_path: str | None = None
    env_template: str = ""
    file_templates: tuple[FileTemplateSpec, ...] = ()
    secret_mappings: tuple[SecretMappingSpec, ...] = ()
    secret_resolver: str | None = None
    secret_config_template: str = ""
    gitignore_entries: tuple[str, ...] = ()
    parameters: tuple[ParameterSpec, ...] = ()
    profiles: tuple[AdapterProfileSpec, ...] = ()
    dependency_extra: str | None = None
    entity_scoped: bool = True

    def has_config(self) -> bool:
        return self.config_path is not None and bool(self.config_template)

    def has_env(self) -> bool:
        return self.env_path is not None and bool(self.env_template)

    def has_file_templates(self) -> bool:
        return bool(self.file_templates)

    def has_secret_mappings(self) -> bool:
        return bool(self.secret_mappings)

    def has_secret_config(self) -> bool:
        return bool(self.secret_config_template)

    def get_profile(self, name: str) -> AdapterProfileSpec | None:
        normalized = name.strip().lower()
        return next(
            (profile for profile in self.profiles if profile.name == normalized),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "layer": self.layer,
            "description": self.description,
            "config_path": self.config_path,
            "merge_config_templates": [
                file_template.to_dict() for file_template in self.merge_config_templates
            ],
            "env_path": self.env_path,
            "file_templates": [
                file_template.to_dict() for file_template in self.file_templates
            ],
            "secret_mappings": [
                secret_mapping.to_dict() for secret_mapping in self.secret_mappings
            ],
            "secret_resolver": self.secret_resolver,
            "secret_config_template": bool(self.secret_config_template),
            "gitignore_entries": list(self.gitignore_entries),
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "profiles": [profile.to_dict() for profile in self.profiles],
            "dependency_extra": self.dependency_extra,
            "entity_scoped": self.entity_scoped,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    layer: LayerKind
    description: str
    activation_config_key: str | None
    adapters: tuple[AdapterSpec, ...]

    def adapter_names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self.adapters)

    def get_adapter(self, name: str) -> AdapterSpec | None:
        normalized = name.strip().lower()
        for adapter in self.adapters:
            if adapter.name == normalized:
                return adapter
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "description": self.description,
            "activation_config_key": self.activation_config_key,
            "adapters": [adapter.to_dict() for adapter in self.adapters],
        }


REPOSITORY_CAPABILITY = CapabilitySpec(
    name="repository",
    layer="outbound",
    description="Persistance des entités métier derrière un port repository.",
    activation_config_key="repository",
    adapters=(
        AdapterSpec(
            name="memory",
            capability="repository",
            layer="outbound",
            description="Stockage volatile en mémoire pour dev, tests et smoke locaux.",
        ),
        AdapterSpec(
            name="mongodb",
            capability="repository",
            layer="outbound",
            description="Repository MongoDB async avec configuration single-tenant ou multitenant.",
            config_path="config/adapters/outbound/mongodb.yaml",
            config_template="""\
uri: null   # single-tenant: mappez adapters.mongodb.uri via config/secrets.yaml, env ou Vault
db_name: {db_name}   # fallback multitenant si le secret tenant ne fournit pas db_name
collection_name: {collection_name}   # null = nom dérivé de la classe entité
multitenant: {multitenant}   # true = uri/db_name résolus par requête via JWT -> VaultTenantResolver
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.mongodb.uri",
                    secret_key="MONGODB_URI",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="db_name",
                    kind="string",
                    prompt="db_name",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="collection_name",
                    kind="string",
                    prompt="collection_name",
                    default="null",
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="multitenant",
                    default=False,
                ),
            ),
        ),
        AdapterSpec(
            name="duckdb",
            capability="repository",
            layer="outbound",
            description="Repository fichier local pour SQL analytique et démos sans serveur.",
            config_path="config/adapters/outbound/duckdb.yaml",
            config_template="""\
multitenant: false
path: {path}
""",
            parameters=(
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="path",
                    default="data/",
                ),
            ),
        ),
        AdapterSpec(
            name="mariadb",
            capability="repository",
            layer="outbound",
            description="Repository MariaDB async optionnel, pilote par SQLAlchemy et asyncmy.",
            config_path="config/adapters/outbound/mariadb.yaml",
            config_template="""\
url: null   # à mapper via config/secrets.yaml ou resolver env/vault si vous fournissez une URL complète
host: {host}
port: {port}
database: {database}
user: {user}
password: null   # à mapper via config/secrets.yaml ou resolver env/vault
driver: {driver}
table_prefix: "{table_prefix}"
multitenant: false
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.mariadb.url",
                    secret_key="MARIADB_URL",
                ),
                SecretMappingSpec(
                    field_path="adapters.mariadb.password",
                    secret_key="MARIADB_PASSWORD",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="host",
                    default="127.0.0.1",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="port",
                    default="3306",
                ),
                ParameterSpec(
                    name="database",
                    kind="string",
                    prompt="database",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="user",
                    kind="string",
                    prompt="user",
                    default="app",
                ),
                ParameterSpec(
                    name="driver",
                    kind="string",
                    prompt="driver",
                    default="asyncmy",
                ),
                ParameterSpec(
                    name="table_prefix",
                    kind="string",
                    prompt="table_prefix",
                    default="",
                ),
            ),
        ),
        AdapterSpec(
            name="postgresql",
            capability="repository",
            layer="outbound",
            description="Repository PostgreSQL async optionnel, pilote par SQLAlchemy et asyncpg, avec payload JSONB generique.",
            config_path="config/adapters/outbound/postgresql.yaml",
            config_template="""\
url: null   # à mapper via config/secrets.yaml ou resolver env/vault si vous fournissez une URL complète
host: {host}
port: {port}
database: {database}
user: {user}
password: null   # à mapper via config/secrets.yaml ou resolver env/vault
schema: {schema}
driver: {driver}
table_prefix: "{table_prefix}"
multitenant: {multitenant}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.postgresql.url",
                    secret_key="POSTGRESQL_URL",
                ),
                SecretMappingSpec(
                    field_path="adapters.postgresql.password",
                    secret_key="POSTGRESQL_PASSWORD",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="host",
                    default="127.0.0.1",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="port",
                    default="5432",
                ),
                ParameterSpec(
                    name="database",
                    kind="string",
                    prompt="database",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="user",
                    kind="string",
                    prompt="user",
                    default="app",
                ),
                ParameterSpec(
                    name="schema",
                    kind="string",
                    prompt="schema",
                    default="public",
                ),
                ParameterSpec(
                    name="driver",
                    kind="string",
                    prompt="driver",
                    default="asyncpg",
                ),
                ParameterSpec(
                    name="table_prefix",
                    kind="string",
                    prompt="table_prefix",
                    default="",
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="multitenant",
                    default=False,
                ),
            ),
        ),
    ),
)

STORAGE_CAPABILITY = CapabilitySpec(
    name="storage",
    layer="outbound",
    description="Stockage de fichiers et blobs derrière un port FileStoragePort.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="filesystem",
            capability="storage",
            layer="outbound",
            description="Stockage fichier local, typiquement monté dans Docker via un volume.",
            config_path="config/adapters/outbound/storage.yaml",
            config_template="""\
adapter: filesystem
root_path: "{root_path}"
prefix: "{prefix}"
create_root: {create_root}
multitenant: {multitenant}
""",
            parameters=(
                ParameterSpec(
                    name="root_path",
                    kind="string",
                    prompt="Chemin conteneur du dossier de fichiers",
                    default="/data/files",
                ),
                ParameterSpec(
                    name="prefix",
                    kind="string",
                    prompt="Préfixe d'objets",
                    default="",
                ),
                ParameterSpec(
                    name="create_root",
                    kind="boolean",
                    prompt="Créer le dossier racine au démarrage",
                    default=True,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Résoudre le stockage par tenant",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="s3",
            capability="storage",
            layer="outbound",
            description="Stockage objet AWS S3 compatible MinIO via endpoint custom.",
            config_path="config/adapters/outbound/storage.yaml",
            config_template="""\
adapter: s3
# Credentials: chaîne AWS par défaut, variables d'environnement, rôle IAM ou TenantContext.
bucket_name: "{bucket_name}"
prefix: "{prefix}"
region_name: "{region_name}"
endpoint_url: {endpoint_url}
force_path_style: {force_path_style}
multitenant: {multitenant}
""",
            parameters=(
                ParameterSpec(
                    name="bucket_name",
                    kind="string",
                    prompt="Bucket S3",
                    default="my-bucket",
                ),
                ParameterSpec(
                    name="prefix",
                    kind="string",
                    prompt="Préfixe d'objets",
                    default="",
                ),
                ParameterSpec(
                    name="region_name",
                    kind="string",
                    prompt="Région AWS",
                    default="eu-west-3",
                ),
                ParameterSpec(
                    name="endpoint_url",
                    kind="string",
                    prompt="Endpoint S3 custom ou null",
                    default="null",
                ),
                ParameterSpec(
                    name="force_path_style",
                    kind="boolean",
                    prompt="Forcer le path-style S3",
                    default=False,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Résoudre le stockage par tenant",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="azure-blob",
            capability="storage",
            layer="outbound",
            description="Stockage objet Azure Blob Storage.",
            config_path="config/adapters/outbound/storage.yaml",
            config_template="""\
adapter: azure-blob
account_url: "{account_url}"
container_name: "{container_name}"
prefix: "{prefix}"
connection_string: null
account_key: null
sas_token: null
use_default_credential: {use_default_credential}
multitenant: {multitenant}
# Credentials: mappez connection_string, account_key ou sas_token via
# config/secrets.yaml, Vault, ou TenantContext. use_default_credential=true
# délègue à DefaultAzureCredential du SDK Azure.
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.storage.connection_string",
                    secret_key="AZURE_STORAGE_CONNECTION_STRING",
                ),
                SecretMappingSpec(
                    field_path="adapters.storage.account_key",
                    secret_key="AZURE_STORAGE_ACCOUNT_KEY",
                ),
                SecretMappingSpec(
                    field_path="adapters.storage.sas_token",
                    secret_key="AZURE_STORAGE_SAS_TOKEN",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="account_url",
                    kind="string",
                    prompt="URL du compte Azure Blob",
                    default="https://<account>.blob.core.windows.net",
                ),
                ParameterSpec(
                    name="container_name",
                    kind="string",
                    prompt="Container Azure Blob",
                    default="my-container",
                ),
                ParameterSpec(
                    name="prefix",
                    kind="string",
                    prompt="Préfixe d'objets",
                    default="",
                ),
                ParameterSpec(
                    name="use_default_credential",
                    kind="boolean",
                    prompt="Utiliser DefaultAzureCredential",
                    default=False,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Résoudre le stockage par tenant",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="gcs",
            capability="storage",
            layer="outbound",
            description="Stockage objet Google Cloud Storage.",
            config_path="config/adapters/outbound/storage.yaml",
            config_template="""\
adapter: gcs
bucket_name: "{bucket_name}"
prefix: "{prefix}"
project_id: {project_id}
credentials_path: null
credentials_json: null
credentials_json_b64: null
multitenant: {multitenant}
# Credentials: use ADC/GOOGLE_APPLICATION_CREDENTIALS, config/secrets.yaml,
# Vault, or TenantContext. Never commit service account JSON.
""",
            parameters=(
                ParameterSpec(
                    name="bucket_name",
                    kind="string",
                    prompt="Bucket Google Cloud Storage",
                    default="my-bucket",
                ),
                ParameterSpec(
                    name="prefix",
                    kind="string",
                    prompt="Préfixe d'objets",
                    default="",
                ),
                ParameterSpec(
                    name="project_id",
                    kind="string",
                    prompt="Project ID GCP ou null",
                    default="null",
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Résoudre le stockage par tenant",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
    ),
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

API_CAPABILITY = CapabilitySpec(
    name="api",
    layer="inbound",
    description="Transport HTTP REST expose via FastAPI.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="fastapi",
            capability="api",
            layer="inbound",
            description="Application FastAPI configurée par Arclith.fastapi().",
            config_path="config/adapters/inbound/fastapi.yaml",
            config_template="""\
host: {host}
port: {port}
reload: {reload}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host FastAPI",
                    default="0.0.0.0",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port FastAPI",
                    default="8000",
                ),
                ParameterSpec(
                    name="reload",
                    kind="boolean",
                    prompt="Activer le reload FastAPI",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

MCP_CAPABILITY = CapabilitySpec(
    name="mcp",
    layer="inbound",
    description="Transport MCP expose via FastMCP.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="fastmcp",
            capability="mcp",
            layer="inbound",
            description="Serveur FastMCP configuré par Arclith.fastmcp() et les runners MCP.",
            config_path="config/adapters/inbound/fastmcp.yaml",
            config_template="""\
host: {host}
port: {port}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host FastMCP",
                    default="127.0.0.1",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port FastMCP",
                    default="8001",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

PROBE_CAPABILITY = CapabilitySpec(
    name="probe",
    layer="inbound",
    description="Serveur de probes health, readiness, info et metrics.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="server",
            capability="probe",
            layer="inbound",
            description="Serveur HTTP transverse exposant /health, /ready, /info et /metrics.",
            config_path="config/adapters/inbound/probe.yaml",
            config_template="""\
host: {host}
port: {port}
enabled: {enabled}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host du serveur de probes",
                    default="0.0.0.0",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port du serveur de probes",
                    default="9000",
                ),
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le serveur de probes",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

HTTP_CAPABILITY = CapabilitySpec(
    name="http",
    layer="inbound",
    description="Middlewares HTTP transverses pour FastAPI.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="idempotency",
            capability="http",
            layer="inbound",
            description="Middleware Idempotency-Key pour éviter les doubles mutations POST.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
idempotency:
  enabled: {enabled}
  ttl_seconds: {ttl_seconds}
  required: {required}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le middleware idempotency",
                    default=True,
                ),
                ParameterSpec(
                    name="ttl_seconds",
                    kind="string",
                    prompt="TTL idempotency en secondes",
                    default="86400",
                ),
                ParameterSpec(
                    name="required",
                    kind="boolean",
                    prompt="Exiger Idempotency-Key sur les POST",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="etag",
            capability="http",
            layer="inbound",
            description="Middleware ETag et If-None-Match pour les lectures GET cacheables.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
etag:
  enabled: {enabled}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le middleware ETag",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="cache-control",
            capability="http",
            layer="inbound",
            description="Directives Cache-Control FastAPI pour lectures GET et mutations.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
cache_control:
  get_single_max_age: {get_single_max_age}
  get_list_max_age: {get_list_max_age}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="get_single_max_age",
                    kind="string",
                    prompt="TTL Cache-Control des GET ressource unique",
                    default="300",
                ),
                ParameterSpec(
                    name="get_list_max_age",
                    kind="string",
                    prompt="TTL Cache-Control des GET collection",
                    default="60",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

COMMAND_BUS_CAPABILITY = CapabilitySpec(
    name="command-bus",
    layer="bidirectional",
    description="Bus de commandes applicatives use-case first.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="rabbitmq",
            capability="command-bus",
            layer="bidirectional",
            description="Worker et publisher RabbitMQ avec ack manuel, confirms, prefetch borne et DLX.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/command_bus.yaml",
                    template="""\
enabled:
  - rabbitmq
rabbitmq:
  url: "{url}"
  exchange: "{exchange}"
  exchange_type: "{exchange_type}"
  queue: "{queue}"
  routing_key: "{routing_key}"
  prefetch: {prefetch}
  consumer_name: "{consumer_name}"
  concurrency: {concurrency}
  publisher_confirms: {publisher_confirms}
  durable: {durable}
  retry_enabled: {retry_enabled}
  retry_requeue: {retry_requeue}
  dead_letter_exchange: "{dead_letter_exchange}"
  dead_letter_routing_key: "{dead_letter_routing_key}"
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="url",
                    kind="string",
                    prompt="URL RabbitMQ",
                    default="amqp://guest:guest@127.0.0.1:5672/",
                ),
                ParameterSpec(
                    name="exchange",
                    kind="string",
                    prompt="Exchange commandes",
                    default="arclith.commands",
                ),
                ParameterSpec(
                    name="exchange_type",
                    kind="string",
                    prompt="Type d'exchange",
                    default="topic",
                    choices=("direct", "topic"),
                ),
                ParameterSpec(
                    name="queue",
                    kind="string",
                    prompt="Queue worker",
                    default="arclith.commands",
                ),
                ParameterSpec(
                    name="routing_key",
                    kind="string",
                    prompt="Routing key",
                    default="commands",
                ),
                ParameterSpec(
                    name="prefetch",
                    kind="string",
                    prompt="Prefetch RabbitMQ borne",
                    default="10",
                ),
                ParameterSpec(
                    name="consumer_name",
                    kind="string",
                    prompt="Consumer name",
                    default="arclith-command-worker",
                ),
                ParameterSpec(
                    name="concurrency",
                    kind="string",
                    prompt="Concurrence worker",
                    default="1",
                ),
                ParameterSpec(
                    name="publisher_confirms",
                    kind="boolean",
                    prompt="Activer publisher confirms",
                    default=True,
                ),
                ParameterSpec(
                    name="durable",
                    kind="boolean",
                    prompt="Déclarer exchange/queue durables",
                    default=True,
                ),
                ParameterSpec(
                    name="retry_enabled",
                    kind="boolean",
                    prompt="Activer DLX/retry",
                    default=True,
                ),
                ParameterSpec(
                    name="retry_requeue",
                    kind="boolean",
                    prompt="Requeue sur erreur handler",
                    default=False,
                ),
                ParameterSpec(
                    name="dead_letter_exchange",
                    kind="string",
                    prompt="Exchange DLX",
                    default="arclith.commands.dlx",
                ),
                ParameterSpec(
                    name="dead_letter_routing_key",
                    kind="string",
                    prompt="Routing key DLX",
                    default="commands.dead",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

RUNTIME_CAPABILITY = CapabilitySpec(
    name="runtime",
    layer="runtime",
    description="Runtime de déploiement standardisé pour images et processus Arclith.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="docker-image",
            capability="runtime",
            layer="runtime",
            description="Dockerfile multi-stage non-root et entrypoint arclith-run multi-transport.",
            file_templates=(
                FileTemplateSpec(path="Dockerfile", template=DOCKERFILE_TEMPLATE),
                FileTemplateSpec(path=".dockerignore", template=DOCKERIGNORE_TEMPLATE),
                FileTemplateSpec(path="arclith-run", template=ARCLITH_RUN_TEMPLATE),
            ),
            parameters=(
                ParameterSpec(
                    name="uv_version",
                    kind="string",
                    prompt="Version uv pinnee dans le builder Docker",
                    default=DEFAULT_UV_VERSION,
                ),
                ParameterSpec(
                    name="api_port",
                    kind="string",
                    prompt="Port expose FastAPI",
                    default=DEFAULT_API_PORT,
                ),
                ParameterSpec(
                    name="mcp_port",
                    kind="string",
                    prompt="Port expose FastMCP",
                    default=DEFAULT_MCP_PORT,
                ),
                ParameterSpec(
                    name="probe_port",
                    kind="string",
                    prompt="Port expose probes /health",
                    default=DEFAULT_PROBE_PORT,
                ),
                ParameterSpec(
                    name="agent_port",
                    kind="string",
                    prompt="Port expose LangGraph agent",
                    default=DEFAULT_AGENT_PORT,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

AUTH_CAPABILITY = CapabilitySpec(
    name="auth",
    layer="inbound",
    description="Authentification JWT Keycloak mutualisée FastAPI et FastMCP.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="keycloak",
            capability="auth",
            layer="inbound",
            description="JWT RS256 via JWKS Keycloak et Swagger UI OAuth2 PKCE.",
            config_path="config/adapters/inbound/keycloak.yaml",
            config_template="""\
url: "{url}"
realm: "{realm}"
audience: {audience}
client_id: {client_id}
""",
            parameters=(
                ParameterSpec(
                    name="url",
                    kind="string",
                    prompt="URL Keycloak",
                    default="http://localhost:8080",
                ),
                ParameterSpec(
                    name="realm",
                    kind="string",
                    prompt="Realm Keycloak",
                    default="rekipe",
                ),
                ParameterSpec(
                    name="audience",
                    kind="string",
                    prompt="Audience JWT attendue",
                    default="null",
                ),
                ParameterSpec(
                    name="client_id",
                    kind="string",
                    prompt="Client public Swagger UI PKCE",
                    default="null",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

TENANT_CAPABILITY = CapabilitySpec(
    name="tenant",
    layer="inbound",
    description="Résolution tenant multitenant depuis un claim JWT.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="vault",
            capability="tenant",
            layer="inbound",
            description="Tenant resolver Vault KV v2 pour coordonnées par adapter.",
            config_path="config/adapters/inbound/tenant.yaml",
            config_template="""\
vault_addr: "{addr}"
vault_mount: "{mount}"
vault_path_prefix: "{path_prefix}"
tenant_claim: "{tenant_claim}"
""",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/adapters/inbound/cache.yaml",
                    template="""\
tenant_uri_ttl: {tenant_uri_ttl}
""",
                ),
            ),
            parameters=(
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
                    name="path_prefix",
                    kind="string",
                    prompt="Préfixe Vault des tenants",
                    default="rekipe/tenants",
                ),
                ParameterSpec(
                    name="tenant_claim",
                    kind="string",
                    prompt="Claim JWT tenant",
                    default="sub",
                ),
                ParameterSpec(
                    name="tenant_uri_ttl",
                    kind="string",
                    prompt="TTL cache tenant en secondes",
                    default="300",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

LICENSE_CAPABILITY = CapabilitySpec(
    name="license",
    layer="inbound",
    description="Validation d'accès par rôle realm Keycloak.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="role",
            capability="license",
            layer="inbound",
            description="Vérifie un rôle dans realm_access.roles via RoleLicenseValidator.",
            config_path="config/adapters/inbound/license.yaml",
            config_template="""\
role: "{role}"
""",
            parameters=(
                ParameterSpec(
                    name="role",
                    kind="string",
                    prompt="Rôle realm Keycloak requis",
                    default="rekipe:licensed",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

LLM_CAPABILITY = CapabilitySpec(
    name="llm",
    layer="outbound",
    description="Configuration LLM pour interpréteurs d'intention et agents via une factory Arclith.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="lmstudio",
            capability="llm",
            layer="outbound",
            description="LLM local LM Studio exposé par l'API OpenAI-compatible.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: openai
model_name: "{model_name}"
api_key: "{api_key}"
base_url: "{base_url}"
""",
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Model ID LM Studio",
                    default="remplacer-par-le-model-id-lm-studio",
                ),
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Endpoint OpenAI-compatible LM Studio",
                    default="http://127.0.0.1:1234/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="API key LM Studio",
                    default="lm-studio",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="openai",
            capability="llm",
            layer="outbound",
            description="Modèle OpenAI via protocole OpenAI-compatible.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: openai
model_name: "{model_name}"
api_key: ""
base_url: "{base_url}"
""",
            env_path=".env",
            env_template="""\
OPENAI_API_KEY={api_key}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.lm.api_key",
                    secret_key="OPENAI_API_KEY",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Modèle OpenAI",
                    default="remplacer-par-model-id-openai",
                ),
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Endpoint OpenAI-compatible",
                    default="https://api.openai.com/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="OPENAI_API_KEY",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="anthropic",
            capability="llm",
            layer="outbound",
            description="Modèle Anthropic pour interpréteurs d'intention et agents.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: anthropic
model_name: "{model_name}"
api_key: ""
""",
            env_path=".env",
            env_template="""\
ANTHROPIC_API_KEY={api_key}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.lm.api_key",
                    secret_key="ANTHROPIC_API_KEY",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Modèle Anthropic",
                    default="remplacer-par-model-id-anthropic",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="ANTHROPIC_API_KEY",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

AGENT_CAPABILITY = CapabilitySpec(
    name="agent",
    layer="inbound",
    description="Adapter agent qui expose les cas d'usage métier via un runtime IA.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="langgraph",
            capability="agent",
            layer="inbound",
            description="Entrypoint LangGraph Studio basé sur la tuyauterie Arclith.",
            config_path="config/adapters/inbound/langgraph.yaml",
            config_template="""\
name: "{graph_name}"
graph: "{graph_name}"
entrypoint: "{langgraph_entrypoint}"
env: ".env"
stream_mode: {stream_mode_yaml}
""",
            file_templates=(
                FileTemplateSpec(
                    path="langgraph.json",
                    template="""\
{{
  "dependencies": ["."],
  "graphs": {{
    "{graph_name}": "{langgraph_entrypoint}"
  }},
  "env": ".env"
}}
""",
                ),
                FileTemplateSpec(
                    path="{package_path}/adapters/inbound/langgraph/__init__.py",
                    template="",
                ),
                FileTemplateSpec(
                    path="{package_path}/adapters/inbound/langgraph/agent.py",
                    template="""\
from typing import Any, TypedDict

from arclith import Arclith
from langgraph.config import get_stream_writer
from langgraph.graph import END, START


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]


arclith = Arclith("config")


# Template minimal volontaire: remplacer AgentState, run_agent et les edges par
# l'état, les noeuds et les transitions propres au projet.
async def run_agent(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    writer({{"kind": "progress", "stage": "agent.started", "message": "Agent node started."}})
    return state


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="{graph_name}")
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="graph_name",
                    kind="string",
                    prompt="Nom du graphe LangGraph",
                    default="agent",
                ),
                ParameterSpec(
                    name="stream_mode",
                    kind="string",
                    prompt="Mode(s) de streaming LangGraph",
                    default="updates",
                    choices=(
                        "values",
                        "updates",
                        "custom",
                        "messages",
                        "checkpoints",
                        "tasks",
                        "debug",
                    ),
                    csv_choices=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)


AGENT_PERSISTENCE_CAPABILITY = CapabilitySpec(
    name="agent-persistence",
    layer="inbound",
    description="Checkpoints de threads et memoire cross-thread pour LangGraph.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="langgraph",
            capability="agent-persistence",
            layer="inbound",
            description="Persistance LangGraph optionnelle, configurable et extensible.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/adapters/inbound/langgraph.yaml",
                    template="{persistence_config_yaml}\n",
                    preserve_existing=True,
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="mode",
                    kind="string",
                    prompt="Mode de persistance LangGraph",
                    default="auto",
                    choices=("auto", "embedded", "agent_server"),
                ),
                ParameterSpec(
                    name="checkpointer",
                    kind="string",
                    prompt="Backend de checkpoints",
                    default="memory",
                    choices=(
                        "none",
                        "memory",
                        "sqlite",
                        "postgresql",
                        "mongodb",
                        "custom",
                    ),
                ),
                ParameterSpec(
                    name="store",
                    kind="string",
                    prompt="Backend de memoire cross-thread",
                    default="memory",
                    choices=(
                        "none",
                        "memory",
                        "postgresql",
                        "mongodb",
                        "redis",
                        "custom",
                    ),
                ),
                ParameterSpec(
                    name="checkpointer_setup",
                    kind="boolean",
                    prompt="Executer setup() pour le checkpointer",
                    default=False,
                ),
                ParameterSpec(
                    name="store_setup",
                    kind="boolean",
                    prompt="Executer setup() pour le store",
                    default=False,
                ),
                ParameterSpec(
                    name="ttl_seconds",
                    kind="string",
                    prompt="TTL des checkpoints en secondes (vide = illimite)",
                    default="",
                ),
                ParameterSpec(
                    name="sqlite_path",
                    kind="string",
                    prompt="Fichier SQLite des checkpoints",
                    default=".arclith/langgraph-checkpoints.sqlite",
                ),
                ParameterSpec(
                    name="database",
                    kind="string",
                    prompt="Base de persistance LangGraph",
                    default="langgraph",
                ),
                ParameterSpec(
                    name="namespace_template",
                    kind="string",
                    prompt="Template de namespace long-term memory",
                    default="{tenant_id}:{user_id}:memories",
                ),
                ParameterSpec(
                    name="checkpointer_factory",
                    kind="string",
                    prompt="Import path de la factory custom checkpointer",
                    default="",
                ),
                ParameterSpec(
                    name="store_factory",
                    kind="string",
                    prompt="Import path de la factory custom store",
                    default="",
                ),
            ),
            entity_scoped=False,
        ),
    ),
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
            description="Export OTLP traces/metrics et instrumentation FastAPI.",
            config_path="config/adapters/outbound/opentelemetry.yaml",
            config_template="""\
service_name: "{service_name}"
endpoint: "{endpoint}"
traces_endpoint: {traces_endpoint}
metrics_endpoint: {metrics_endpoint}
protocol: "{protocol}"
headers_env: OTEL_EXPORTER_OTLP_HEADERS
traces: {traces}
metrics: {metrics}
instrument_fastapi: {instrument_fastapi}
metrics_export_interval_millis: {metrics_export_interval_millis}
""",
            env_path=".env",
            env_template="""\
OTEL_SERVICE_NAME={service_name}
OTEL_EXPORTER_OTLP_ENDPOINT={endpoint}
OTEL_EXPORTER_OTLP_PROTOCOL={protocol}
OTEL_EXPORTER_OTLP_HEADERS={headers}
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
                    name="traces_endpoint",
                    kind="string",
                    prompt="OTLP traces endpoint",
                    default="null",
                ),
                ParameterSpec(
                    name="metrics_endpoint",
                    kind="string",
                    prompt="OTLP metrics endpoint",
                    default="null",
                ),
                ParameterSpec(
                    name="protocol",
                    kind="string",
                    prompt="OTLP protocol",
                    default="http/protobuf",
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
                    name="instrument_fastapi",
                    kind="boolean",
                    prompt="Instrumenter FastAPI",
                    default=True,
                ),
                ParameterSpec(
                    name="metrics_export_interval_millis",
                    kind="string",
                    prompt="Intervalle export métriques en ms",
                    default="60000",
                ),
                ParameterSpec(
                    name="headers",
                    kind="string",
                    prompt="OTEL_EXPORTER_OTLP_HEADERS",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

CAPABILITY_CATALOG = (
    REPOSITORY_CAPABILITY,
    STORAGE_CAPABILITY,
    CACHE_CAPABILITY,
    LOGGER_CAPABILITY,
    SECRETS_CAPABILITY,
    API_CAPABILITY,
    MCP_CAPABILITY,
    PROBE_CAPABILITY,
    HTTP_CAPABILITY,
    COMMAND_BUS_CAPABILITY,
    RUNTIME_CAPABILITY,
    AUTH_CAPABILITY,
    TENANT_CAPABILITY,
    LICENSE_CAPABILITY,
    LLM_CAPABILITY,
    AGENT_CAPABILITY,
    AGENT_PERSISTENCE_CAPABILITY,
    OBSERVABILITY_CAPABILITY,
)


def get_capability(name: str) -> CapabilitySpec | None:
    normalized = name.strip().lower()
    for capability in CAPABILITY_CATALOG:
        if capability.name == normalized:
            return capability
    return None


def capability_names() -> tuple[str, ...]:
    return tuple(capability.name for capability in CAPABILITY_CATALOG)


def repository_adapter_names() -> tuple[str, ...]:
    return REPOSITORY_CAPABILITY.adapter_names()


def capability_catalog_as_dict() -> list[dict[str, Any]]:
    return [capability.to_dict() for capability in CAPABILITY_CATALOG]
