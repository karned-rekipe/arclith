import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote_plus

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PostgreSQLConfig:
    url: str | None = None
    host: str = "127.0.0.1"
    port: int = 5432
    database: str | None = None
    user: str = "app"
    password: str | None = None
    schema: str = "public"
    driver: str = "asyncpg"
    table_prefix: str = ""

    def __post_init__(self) -> None:
        _validate_port(self.port)
        _validate_identifier("schema", self.schema, allow_empty=False)
        _validate_identifier("table_prefix", self.table_prefix, allow_empty=True)
        _validate_driver(self.driver)

    def connection_url(self) -> str:
        if self.url:
            return self.url
        if not self.database:
            raise ValueError(
                "PostgreSQL database is required when url is not configured"
            )

        auth = quote_plus(self.user)
        if self.password:
            auth = f"{auth}:{quote_plus(self.password)}"
        database = quote_plus(self.database)
        return f"postgresql+{self.driver}://{auth}@{self.host}:{self.port}/{database}"

    def with_tenant_params(self, params: Mapping[str, str]) -> "PostgreSQLConfig":
        return PostgreSQLConfig(
            url=_first_value(params, "url", "uri", default=self.url),
            host=_string_value(params, "host", default=self.host),
            port=_port_value(params, self.port),
            database=_first_value(params, "database", "db_name", default=self.database),
            user=_string_value(params, "user", "username", default=self.user),
            password=_first_value(params, "password", default=self.password),
            schema=_string_value(params, "schema", default=self.schema),
            driver=_string_value(params, "driver", default=self.driver),
            table_prefix=_string_value(
                params, "table_prefix", default=self.table_prefix
            ),
        )


def _first_value(
    params: Mapping[str, str], *names: str, default: str | None
) -> str | None:
    for name in names:
        raw_value = params.get(name)
        value = raw_value.strip() if raw_value is not None else None
        if value:
            return value
    return default


def _string_value(params: Mapping[str, str], *names: str, default: str) -> str:
    value = _first_value(params, *names, default=default)
    return value or default


def _port_value(params: Mapping[str, str], default: int) -> int:
    raw_value = params.get("port")
    value = raw_value.strip() if raw_value is not None else ""
    if not value:
        return default
    if not value.isdigit():
        raise ValueError("PostgreSQL port must be an integer")
    return _validate_port(int(value))


def _validate_port(port: int) -> int:
    if port <= 0 or port > 65535:
        raise ValueError("PostgreSQL port must be between 1 and 65535")
    return port


def _validate_identifier(name: str, value: str, *, allow_empty: bool) -> None:
    if allow_empty and not value:
        return
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"PostgreSQL {name} must be a safe SQL identifier")


def _validate_driver(driver: str) -> None:
    if not re.fullmatch(r"^[A-Za-z0-9_]+$", driver):
        raise ValueError("PostgreSQL driver must be a safe SQLAlchemy driver token")
