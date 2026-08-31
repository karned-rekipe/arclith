from __future__ import annotations

import re
from pathlib import Path
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from arclith.infrastructure.settings._base import SettingsModel

_DUCKDB_SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json", ".arrow"}
_SQL_IDENTIFIER_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"


class MongoDBSettings(SettingsModel):
    uri: str | None = None
    db_name: str
    collection_name: str | None = None
    multitenant: bool = False


class DuckDBSettings(SettingsModel):
    path: str
    multitenant: bool = False

    @field_validator("path")
    @classmethod
    def must_be_supported_format(cls, v: str) -> str:
        p = Path(v)
        if p.is_dir() or v.endswith("/"):
            return v
        ext = p.suffix.lower()
        if ext not in _DUCKDB_SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Format '{ext}' non supporté par DuckDB. "
                f"Formats acceptés : {', '.join(sorted(_DUCKDB_SUPPORTED_EXTENSIONS))}"
            )
        return v


class _SQLRepositorySettings(SettingsModel):
    url: str | None = None
    host: str = "127.0.0.1"
    port: int
    database: str | None = None
    user: str = "app"
    password: str | None = None
    driver: str
    table_prefix: str = ""
    multitenant: bool = False

    @field_validator("port")
    @classmethod
    def must_be_valid_port(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError("port doit etre compris entre 1 et 65535")
        return v

    @model_validator(mode="after")
    def validate_connection_target(self) -> Self:
        if self.multitenant:
            return self
        if not self.url and not self.database:
            raise ValueError("database est requis quand url n'est pas configure")
        return self


class MariaDBSettings(_SQLRepositorySettings):
    port: int = 3306
    driver: str = "asyncmy"


class PostgreSQLSettings(_SQLRepositorySettings):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    port: int = 5432
    schema_name: str = Field(default="public", alias="schema")
    driver: str = "asyncpg"

    @field_validator("schema_name")
    @classmethod
    def must_be_safe_schema(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("schema PostgreSQL ne doit pas etre vide")
        if not re.fullmatch(_SQL_IDENTIFIER_RE, value):
            raise ValueError("schema PostgreSQL doit etre un identifiant SQL sur")
        return value

    @field_validator("table_prefix")
    @classmethod
    def must_be_safe_table_prefix(cls, v: str) -> str:
        value = v.strip()
        if value and not re.fullmatch(_SQL_IDENTIFIER_RE, value):
            raise ValueError(
                "table_prefix PostgreSQL doit etre vide ou un identifiant SQL sur"
            )
        return value

    @field_validator("driver")
    @classmethod
    def must_be_safe_driver(cls, v: str) -> str:
        value = v.strip()
        if not re.fullmatch(r"^[A-Za-z0-9_]+$", value):
            raise ValueError("driver PostgreSQL doit etre un token SQLAlchemy sur")
        return value
