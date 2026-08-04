import pytest

from arclith.adapters.outbound.mariadb.config import MariaDBConfig


def test_connection_url_encodes_credentials() -> None:
    config = MariaDBConfig(database="tenant db", user="app user", password="s e+c/r/e/t")

    assert config.connection_url() == "mysql+asyncmy://app+user:s+e%2Bc%2Fr%2Fe%2Ft@127.0.0.1:3306/tenant+db"


def test_with_tenant_params_accepts_password() -> None:
    config = MariaDBConfig(database="default").with_tenant_params({"database": "tenant", "password": "secret"})

    assert config.password == "secret"
    assert config.connection_url() == "mysql+asyncmy://app:secret@127.0.0.1:3306/tenant"


@pytest.mark.parametrize(
    ("raw_port", "expected"),
    [
        ("3307", 3307),
        (" 3307 ", 3307),
        ("", 3306),
        ("   ", 3306),
    ],
)
def test_with_tenant_params_parses_port(raw_port: str, expected: int) -> None:
    config = MariaDBConfig(database="demo").with_tenant_params({"port": raw_port})

    assert config.port == expected


@pytest.mark.parametrize("raw_port", ["0", "65536", "-1", "abc", "33.07"])
def test_with_tenant_params_rejects_invalid_port(raw_port: str) -> None:
    with pytest.raises(ValueError, match="MariaDB port"):
        MariaDBConfig(database="demo").with_tenant_params({"port": raw_port})
