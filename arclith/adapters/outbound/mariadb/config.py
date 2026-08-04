from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class MariaDBConfig:
    url: str | None = None
    host: str = "127.0.0.1"
    port: int = 3306
    database: str | None = None
    user: str = "app"
    password: str | None = None
    driver: str = "asyncmy"
    table_prefix: str = ""

    def connection_url(self) -> str:
        if self.url:
            return self.url
        if not self.database:
            raise ValueError("MariaDB database is required when url is not configured")

        auth = quote_plus(self.user)
        if self.password:
            auth = f"{auth}:{quote_plus(self.password)}"
        database = quote_plus(self.database)
        return f"mysql+{self.driver}://{auth}@{self.host}:{self.port}/{database}"

    def with_tenant_params(self, params: Mapping[str, str]) -> "MariaDBConfig":
        return MariaDBConfig(
            url=_first_value(params, "url", "uri", default=self.url),
            host=_string_value(params, "host", default=self.host),
            port=_port_value(params, self.port),
            database=_first_value(params, "database", "db_name", default=self.database),
            user=_string_value(params, "user", "username", default=self.user),
            password=_first_value(params, "password", default=self.password),
            driver=_string_value(params, "driver", default=self.driver),
            table_prefix=_string_value(params, "table_prefix", default=self.table_prefix),
        )


def _first_value(params: Mapping[str, str], *names: str, default: str | None) -> str | None:
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
        raise ValueError("MariaDB port must be an integer")
    port = int(value)
    if port <= 0 or port > 65535:
        raise ValueError("MariaDB port must be between 1 and 65535")
    return port
