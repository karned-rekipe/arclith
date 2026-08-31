from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    ParameterSpec,
    SecretMappingSpec,
)

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
