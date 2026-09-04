from arclith_cli.capability_models import (
    AdapterSpec,
    ParameterSpec,
    SecretMappingSpec,
)
from arclith_cli.catalogs.repository_facets import POSTGRESQL_FACETS

POSTGRESQL_REPOSITORY_ADAPTER = AdapterSpec(
    name="postgresql",
    capability="repository",
    layer="outbound",
    description=(
        "Repository PostgreSQL async optionnel avec JSONB par defaut ou "
        "mapping structure explicite."
    ),
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
mapping_strategy: {mapping_strategy}
auto_create_schema: {auto_create_schema}
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
            name="mapping_strategy",
            kind="string",
            prompt="mapping_strategy",
            default="generic_json",
            choices=("generic_json", "structured"),
        ),
        ParameterSpec(
            name="auto_create_schema",
            kind="boolean",
            prompt="auto_create_schema",
            default=True,
        ),
        ParameterSpec(
            name="multitenant",
            kind="boolean",
            prompt="multitenant",
            default=False,
        ),
    ),
    facets=POSTGRESQL_FACETS,
)

__all__ = ["POSTGRESQL_REPOSITORY_ADAPTER"]
