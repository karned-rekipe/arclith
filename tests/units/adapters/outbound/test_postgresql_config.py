import pytest

from arclith.adapters.outbound.postgresql.config import PostgreSQLConfig


def test_connection_url_encodes_credentials() -> None:
    config = PostgreSQLConfig(
        database="tenant db", user="app user", password="s e+c/r/e/t"
    )

    assert (
        config.connection_url()
        == "postgresql+asyncpg://app+user:s+e%2Bc%2Fr%2Fe%2Ft@127.0.0.1:5432/tenant+db"
    )


def test_with_tenant_params_accepts_aliases_and_schema() -> None:
    config = PostgreSQLConfig(
        database="default",
        mapping_strategy="structured",
        auto_create_schema=False,
    ).with_tenant_params(
        {
            "db_name": "tenant",
            "username": "tenant_user",
            "password": "secret",
            "schema": "tenant_schema",
            "table_prefix": "tenant_",
        }
    )

    assert config.database == "tenant"
    assert config.user == "tenant_user"
    assert config.password == "secret"
    assert config.schema == "tenant_schema"
    assert config.table_prefix == "tenant_"
    assert config.mapping_strategy == "structured"
    assert config.auto_create_schema is False
    assert (
        config.connection_url()
        == "postgresql+asyncpg://tenant_user:secret@127.0.0.1:5432/tenant"
    )


def test_with_tenant_params_accepts_uri_alias() -> None:
    config = PostgreSQLConfig(database="default").with_tenant_params(
        {"uri": "postgresql+asyncpg://tenant@db:5432/tenant"}
    )

    assert config.url == "postgresql+asyncpg://tenant@db:5432/tenant"
    assert config.connection_url() == "postgresql+asyncpg://tenant@db:5432/tenant"


@pytest.mark.parametrize(
    ("raw_port", "expected"),
    [
        ("5433", 5433),
        (" 5433 ", 5433),
        ("", 5432),
        ("   ", 5432),
    ],
)
def test_with_tenant_params_parses_port(raw_port: str, expected: int) -> None:
    config = PostgreSQLConfig(database="demo").with_tenant_params({"port": raw_port})

    assert config.port == expected


@pytest.mark.parametrize("raw_port", ["0", "65536", "-1", "abc", "54.32"])
def test_with_tenant_params_rejects_invalid_port(raw_port: str) -> None:
    with pytest.raises(ValueError, match="PostgreSQL port"):
        PostgreSQLConfig(database="demo").with_tenant_params({"port": raw_port})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema", "unsafe-name"),
        ("table_prefix", "unsafe-name"),
    ],
)
def test_rejects_unsafe_identifiers(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        PostgreSQLConfig(database="demo", **{field_name: value})


def test_connection_url_requires_database_when_url_is_missing() -> None:
    with pytest.raises(ValueError, match="database is required"):
        PostgreSQLConfig(database=None).connection_url()


def test_mapping_defaults_preserve_generic_repository_behavior() -> None:
    config = PostgreSQLConfig(database="demo")

    assert config.mapping_strategy == "generic_json"
    assert config.auto_create_schema is True


def test_config_rejects_unknown_mapping_strategy() -> None:
    with pytest.raises(ValueError, match="mapping_strategy"):
        PostgreSQLConfig(database="demo", mapping_strategy="automatic")
