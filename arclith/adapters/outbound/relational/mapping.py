from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from arclith.domain.models.entity import Entity

T = TypeVar("T", bound=Entity)

RelationalColumnKind = Literal[
    "boolean",
    "date",
    "datetime",
    "float",
    "integer",
    "json",
    "string",
    "uuid",
]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_COLUMN_KINDS = {
    "boolean",
    "date",
    "datetime",
    "float",
    "integer",
    "json",
    "string",
    "uuid",
}
_REQUIRED_COLUMNS = {
    "uuid": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime",
    "deleted_at": "datetime",
    "version": "integer",
}


@dataclass(frozen=True)
class RelationalColumn:
    """Vendor-neutral declaration of one structured relational column."""

    name: str
    kind: RelationalColumnKind
    nullable: bool = False
    primary_key: bool = False
    indexed: bool = False
    unique: bool = False

    def __post_init__(self) -> None:
        _validate_identifier("column", self.name)
        if self.kind not in _SUPPORTED_COLUMN_KINDS:
            supported = ", ".join(sorted(_SUPPORTED_COLUMN_KINDS))
            raise ValueError(
                f"Unsupported relational column kind '{self.kind}'. "
                f"Supported kinds: {supported}."
            )


@dataclass(frozen=True)
class RelationalIndex:
    """Vendor-neutral declaration of a possibly composite index."""

    name: str
    columns: tuple[str, ...]
    unique: bool = False

    def __post_init__(self) -> None:
        _validate_identifier("index", self.name)
        normalized_columns = tuple(self.columns)
        object.__setattr__(self, "columns", normalized_columns)
        if not normalized_columns:
            raise ValueError(f"Relational index '{self.name}' must reference columns")
        if len(set(normalized_columns)) != len(normalized_columns):
            raise ValueError(
                f"Relational index '{self.name}' must not repeat a column"
            )
        for column_name in normalized_columns:
            _validate_identifier("index column", column_name)


class RelationalEntityMapper(Protocol[T]):
    """Application-owned conversion between an entity and a typed SQL record."""

    entity_class: type[T]
    table_name: str
    columns: tuple[RelationalColumn, ...]
    indexes: tuple[RelationalIndex, ...]

    def to_record(self, entity: T) -> Mapping[str, Any]:
        raise NotImplementedError

    def from_record(self, record: Mapping[str, Any]) -> T:
        raise NotImplementedError


def validate_relational_mapper(
    mapper: RelationalEntityMapper[T],
) -> RelationalEntityMapper[T]:
    """Validate the structural contract required by ``Repository[T]``."""

    entity_class = mapper.entity_class
    if not isinstance(entity_class, type) or not issubclass(entity_class, Entity):
        raise ValueError("Relational mapper entity_class must inherit from Entity")
    _validate_identifier("table", mapper.table_name)
    columns_by_name = _validate_columns(mapper)
    _validate_repository_columns(mapper.table_name, columns_by_name)
    _validate_indexes(mapper, set(columns_by_name))
    return mapper


def _validate_columns(
    mapper: RelationalEntityMapper[Any],
) -> dict[str, RelationalColumn]:
    columns = tuple(mapper.columns)
    if not columns:
        raise ValueError(f"Relational mapper '{mapper.table_name}' must declare columns")
    if not all(isinstance(column, RelationalColumn) for column in columns):
        raise ValueError("Relational mapper columns must be RelationalColumn values")

    columns_by_name = {column.name: column for column in columns}
    if len(columns_by_name) != len(columns):
        raise ValueError(
            f"Relational mapper '{mapper.table_name}' has duplicate column names"
        )
    return columns_by_name


def _validate_repository_columns(
    table_name: str,
    columns_by_name: Mapping[str, RelationalColumn],
) -> None:
    missing = sorted(set(_REQUIRED_COLUMNS) - set(columns_by_name))
    if missing:
        raise ValueError(
            f"Relational mapper '{table_name}' is missing Repository columns: "
            f"{', '.join(missing)}"
        )
    for name, expected_kind in _REQUIRED_COLUMNS.items():
        actual_kind = columns_by_name[name].kind
        if actual_kind != expected_kind:
            raise ValueError(
                f"Relational mapper column '{name}' must use kind "
                f"'{expected_kind}', got '{actual_kind}'"
            )

    primary_keys = [
        column.name for column in columns_by_name.values() if column.primary_key
    ]
    if primary_keys != ["uuid"]:
        raise ValueError(
            "Relational mapper must declare 'uuid' as its only primary key"
        )
    if not columns_by_name["deleted_at"].nullable:
        raise ValueError("Relational mapper column 'deleted_at' must be nullable")


def _validate_indexes(
    mapper: RelationalEntityMapper[Any],
    column_names: set[str],
) -> None:
    indexes = tuple(mapper.indexes)
    if not all(isinstance(index, RelationalIndex) for index in indexes):
        raise ValueError("Relational mapper indexes must be RelationalIndex values")
    index_names = [index.name for index in indexes]
    if len(set(index_names)) != len(index_names):
        raise ValueError(
            f"Relational mapper '{mapper.table_name}' has duplicate index names"
        )
    for index in indexes:
        unknown = sorted(set(index.columns) - column_names)
        if unknown:
            raise ValueError(
                f"Relational index '{index.name}' references unknown columns: "
                f"{', '.join(unknown)}"
            )


def _validate_identifier(kind: str, value: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"Relational {kind} name '{value}' must be a safe SQL identifier"
        )


__all__ = [
    "RelationalColumn",
    "RelationalColumnKind",
    "RelationalEntityMapper",
    "RelationalIndex",
]
