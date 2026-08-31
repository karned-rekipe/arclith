from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypeVar

import duckdb
from uuid6 import UUID, uuid7

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound import repository as repository_port

T = TypeVar("T", bound=Entity)

_SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json", ".arrow"}


def _validate_extension(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Format '{ext}' non supporté. "
            f"Formats acceptés : {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )


def _read_file(con: duckdb.DuckDBPyConnection, path: Path) -> duckdb.DuckDBPyRelation:
    ext = path.suffix.lower()
    p = str(path)
    match ext:
        case ".csv":
            return con.read_csv(p)
        case ".parquet":
            return con.read_parquet(p)
        case ".json":
            return con.read_json(p)
        case ".arrow":
            return con.from_arrow(p)
        case _:
            raise ValueError(f"Format non supporté : {ext}")


def _write_file(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    ext = path.suffix.lower()
    p = str(path)
    match ext:
        case ".csv":
            con.execute(f"COPY {table} TO '{p}' (FORMAT CSV, HEADER)")
        case ".parquet":
            con.execute(f"COPY {table} TO '{p}' (FORMAT PARQUET)")
        case ".json":
            con.execute(f"COPY {table} TO '{p}' (FORMAT JSON)")
        case _:
            raise ValueError(f"Écriture non supportée pour le format : {ext}")


class DuckDBRepository(repository_port.Repository[T]):
    _repository_contract = repository_port.Repository

    def __init__(
        self, path: str | Path, entity_class: type[T], default_ext: str = ".csv"
    ) -> None:
        base = Path(path)
        is_dir_path = base.is_dir() or not base.suffix
        self._path = (
            base / f"{entity_class.__name__.lower()}{default_ext}"
            if is_dir_path
            else base
        )
        self._entity_class = entity_class
        self._table = entity_class.__name__.lower()
        _validate_extension(self._path)
        self._con = duckdb.connect()
        if not self._path.exists():
            self._create_empty_file()
        self._load()

    def _create_empty_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        columns = list(self._entity_class.model_fields.keys())
        ext = self._path.suffix.lower()
        match ext:
            case ".csv":
                self._path.write_text(",".join(columns) + "\n")
            case ".json":
                self._path.write_text("[]")
            case _:
                raise FileNotFoundError(
                    f"Fichier introuvable : {self._path}. "
                    f"Création automatique non supportée pour le format '{ext}'."
                )

    # noinspection SqlNoDataSourceInspection
    def _load(self) -> None:
        rel = _read_file(self._con, self._path)  # referenced by name in DuckDB SQL
        self._con.register("rel", rel)
        self._con.execute(f"CREATE OR REPLACE TABLE {self._table} AS SELECT * FROM rel")  # nosec B608

    def _persist(self) -> None:
        _write_file(self._con, self._table, self._path)

    def _row_to_entity(self, row: dict[str, Any]) -> T:
        entity_fields = set(self._entity_class.model_fields.keys())
        cleaned = {k: v for k, v in row.items() if k in entity_fields}
        for k, v in cleaned.items():
            if isinstance(v, str):
                with suppress(ValueError):
                    cleaned[k] = datetime.fromisoformat(v)
        if "uuid" in cleaned and isinstance(cleaned["uuid"], str):
            cleaned["uuid"] = UUID(cleaned["uuid"])
        return self._entity_class(**cleaned)

    def _entity_to_row(self, entity: T) -> dict[str, Any]:
        row = entity.model_dump()
        row["uuid"] = str(row["uuid"])
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        return row

    # noinspection SqlNoDataSourceInspection
    def _fetch(self, sql: str, params: list | None = None) -> list[dict[str, Any]]:
        cur = self._con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # noinspection SqlNoDataSourceInspection
    async def create(self, entity: T) -> T:
        row = self._entity_to_row(entity)
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        self._con.execute(
            f"INSERT INTO {self._table} ({cols}) VALUES ({placeholders})",  # nosec B608
            list(row.values()),
        )
        self._persist()
        return entity

    # noinspection SqlNoDataSourceInspection
    async def read(self, uuid: UUID) -> Optional[T]:
        rows = self._fetch(f"SELECT * FROM {self._table} WHERE uuid = ?", [str(uuid)])  # nosec B608
        return self._row_to_entity(rows[0]) if rows else None

    # noinspection SqlNoDataSourceInspection
    async def update(self, entity: T) -> T:
        row = self._entity_to_row(entity)
        sets = ", ".join(f"{k} = ?" for k in row if k != "uuid")
        values = [v for k, v in row.items() if k != "uuid"] + [str(entity.uuid)]
        self._con.execute(f"UPDATE {self._table} SET {sets} WHERE uuid = ?", values)  # nosec B608
        self._persist()
        return entity

    # noinspection SqlNoDataSourceInspection
    async def delete(self, uuid: UUID) -> None:
        self._con.execute(f"DELETE FROM {self._table} WHERE uuid = ?", [str(uuid)])  # nosec B608
        self._persist()

    # noinspection SqlNoDataSourceInspection
    async def find_all(self) -> list[T]:
        rows = self._fetch(f"SELECT * FROM {self._table} WHERE deleted_at IS NULL")  # nosec B608
        return [self._row_to_entity(r) for r in rows]

    # noinspection SqlNoDataSourceInspection
    async def find_page(
        self, offset: int = 0, limit: int | None = None
    ) -> tuple[list[T], int]:
        """Single-query pagination — COUNT(*) OVER () gives total before offset/limit."""
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        rows = self._fetch(
            f"SELECT *, COUNT(*) OVER () AS __total FROM {self._table} "  # nosec B608
            f"WHERE deleted_at IS NULL ORDER BY rowid OFFSET {offset} {limit_clause}"
        )
        total = int(rows[0]["__total"]) if rows else 0
        return [
            self._row_to_entity({k: v for k, v in r.items() if k != "__total"})
            for r in rows
        ], total

    # noinspection SqlNoDataSourceInspection
    async def find_deleted(self) -> list[T]:
        rows = self._fetch(f"SELECT * FROM {self._table} WHERE deleted_at IS NOT NULL")  # nosec B608
        return [self._row_to_entity(r) for r in rows]

    async def duplicate(self, uuid: UUID) -> T:
        entity = await self.read(uuid)
        if entity is None or entity.is_deleted:
            raise KeyError(f"Entity with uuid {uuid} not found")
        clone = entity.model_copy(update={"uuid": uuid7()})
        return await self.create(clone)
