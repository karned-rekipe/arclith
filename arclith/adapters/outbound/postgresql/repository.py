from asyncio import Lock
from dataclasses import dataclass
from functools import cache
import importlib.util
import json
import re
from typing import Any, Generic, TypeVar

from uuid6 import UUID, uuid7

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.postgresql.config import PostgreSQLConfig
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXTRA_MESSAGE = (
    "PostgreSQL repository requires the optional extra: arclith[postgresql]"
)


@dataclass(frozen=True)
class _SQLAlchemyAPI:
    column: Any
    datetime: Any
    integer: Any
    jsonb: Any
    metadata: Any
    string: Any
    table: Any
    delete: Any
    count: Any
    create_schema: Any
    insert: Any
    select: Any
    update: Any
    create_async_engine: Any


@cache
def _sqlalchemy_api() -> _SQLAlchemyAPI:
    try:
        from sqlalchemy import (
            Column,
            DateTime,
            Integer,
            MetaData,
            String,
            Table,
            delete,
            func,
            insert,
            select,
            update,
        )
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.schema import CreateSchema
    except ModuleNotFoundError as exc:
        raise RuntimeError(_EXTRA_MESSAGE) from exc

    return _SQLAlchemyAPI(
        column=Column,
        datetime=DateTime,
        integer=Integer,
        jsonb=JSONB,
        metadata=MetaData,
        string=String,
        table=Table,
        delete=delete,
        count=func.count,
        create_schema=CreateSchema,
        insert=insert,
        select=select,
        update=update,
        create_async_engine=create_async_engine,
    )


def _require_asyncpg() -> None:
    if importlib.util.find_spec("asyncpg") is None:
        raise RuntimeError(_EXTRA_MESSAGE)


class PostgreSQLRepository(Repository[T], Generic[T]):
    """Generic PostgreSQL repository storing each entity as one JSONB document."""

    def __init__(
        self, config: PostgreSQLConfig, entity_class: type[T], logger: Logger
    ) -> None:
        self._config = config
        self._entity_class = entity_class
        self._logger = logger
        self._tables: dict[str, tuple[Any, Any]] = {}
        self._engines: dict[str, Any] = {}
        self._ready_tables: set[str] = set()
        self._schema_locks: dict[str, Lock] = {}

    def _active_config(self) -> PostgreSQLConfig:
        coords = get_adapter_tenant_context("postgresql")
        if coords is None:
            return self._config
        return self._config.with_tenant_params(coords.params)

    def _table_key(self, config: PostgreSQLConfig) -> str:
        return f"{config.schema}.{config.table_prefix}{self._entity_class.__name__.lower()}"

    def _table_for(self, config: PostgreSQLConfig) -> tuple[Any, Any]:
        table_key = self._table_key(config)
        if table_key not in self._tables:
            self._tables[table_key] = self._build_table(config)
        return self._tables[table_key]

    def _build_table(self, config: PostgreSQLConfig) -> tuple[Any, Any]:
        table_name = f"{config.table_prefix}{self._entity_class.__name__.lower()}"
        if not _IDENTIFIER_RE.fullmatch(table_name):
            raise ValueError(f"Invalid PostgreSQL table name: {table_name}")

        api = _sqlalchemy_api()
        metadata = api.metadata(schema=config.schema)
        table = api.table(
            table_name,
            metadata,
            api.column("uuid", api.string(36), primary_key=True),
            api.column("data", api.jsonb, nullable=False),
            api.column("created_at", api.datetime(timezone=True), nullable=False),
            api.column("updated_at", api.datetime(timezone=True), nullable=False),
            api.column("deleted_at", api.datetime(timezone=True), nullable=True),
            api.column("version", api.integer, nullable=False),
        )
        return metadata, table

    def _engine_for(self, url: str, table_name: str, driver: str) -> Any:
        if url not in self._engines:
            if driver == "asyncpg":
                _require_asyncpg()
            self._engines[url] = _sqlalchemy_api().create_async_engine(
                url, pool_pre_ping=True
            )
            self._logger.debug("PostgreSQL engine created", table=table_name)
        return self._engines[url]

    def _schema_lock_for(self, url: str) -> Lock:
        if url not in self._schema_locks:
            self._schema_locks[url] = Lock()
        return self._schema_locks[url]

    async def _ensure_schema(
        self, engine: Any, url: str, metadata: Any, table_key: str
    ) -> None:
        ready_key = f"{url}|{table_key}"
        if ready_key in self._ready_tables:
            return

        async with self._schema_lock_for(url):
            if ready_key in self._ready_tables:
                return
            async with engine.begin() as connection:
                if metadata.schema != "public":
                    await connection.execute(
                        _sqlalchemy_api().create_schema(
                            metadata.schema, if_not_exists=True
                        )
                    )
                await connection.run_sync(metadata.create_all)
            self._ready_tables.add(ready_key)

    async def _engine_and_table(self) -> tuple[Any, Any]:
        config = self._active_config()
        url = config.connection_url()
        metadata, table = self._table_for(config)
        engine = self._engine_for(url, table.name, config.driver)
        await self._ensure_schema(engine, url, metadata, self._table_key(config))
        return engine, table

    def _entity_values(self, entity: T) -> dict[str, Any]:
        return {
            "uuid": str(entity.uuid),
            "data": entity.model_dump(mode="json"),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def _row_to_entity(self, row: Any) -> T:
        payload = row["data"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("PostgreSQL repository row payload must be a JSON object")
        return self._entity_class(**payload)

    async def create(self, entity: T) -> T:
        engine, table = await self._engine_and_table()
        async with engine.begin() as connection:
            await connection.execute(
                _sqlalchemy_api().insert(table).values(**self._entity_values(entity))
            )
        return entity

    async def read(self, uuid: UUID) -> T | None:
        engine, table = await self._engine_and_table()
        statement = (
            _sqlalchemy_api().select(table.c.data).where(table.c.uuid == str(uuid))
        )
        async with engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().first()
        return self._row_to_entity(row) if row is not None else None

    async def update(self, entity: T) -> T:
        engine, table = await self._engine_and_table()
        values = self._entity_values(entity)
        values.pop("uuid")
        statement = (
            _sqlalchemy_api()
            .update(table)
            .where(table.c.uuid == str(entity.uuid))
            .values(**values)
        )
        async with engine.begin() as connection:
            await connection.execute(statement)
        return entity

    async def delete(self, uuid: UUID) -> None:
        engine, table = await self._engine_and_table()
        statement = _sqlalchemy_api().delete(table).where(table.c.uuid == str(uuid))
        async with engine.begin() as connection:
            await connection.execute(statement)

    async def find_all(self) -> list[T]:
        engine, table = await self._engine_and_table()
        statement = (
            _sqlalchemy_api()
            .select(table.c.data)
            .where(table.c.deleted_at.is_(None))
            .order_by(table.c.created_at, table.c.uuid)
        )
        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [self._row_to_entity(row) for row in rows]

    async def find_page(
        self, offset: int = 0, limit: int | None = None
    ) -> tuple[list[T], int]:
        engine, table = await self._engine_and_table()
        statement = (
            _sqlalchemy_api()
            .select(table.c.data, _sqlalchemy_api().count().over().label("__total"))
            .where(table.c.deleted_at.is_(None))
            .order_by(table.c.created_at, table.c.uuid)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)

        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()

        total = int(rows[0]["__total"]) if rows else 0
        return [self._row_to_entity(row) for row in rows], total

    async def find_deleted(self) -> list[T]:
        engine, table = await self._engine_and_table()
        statement = (
            _sqlalchemy_api()
            .select(table.c.data)
            .where(table.c.deleted_at.is_not(None))
            .order_by(table.c.deleted_at, table.c.uuid)
        )
        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [self._row_to_entity(row) for row in rows]

    async def duplicate(self, uuid: UUID) -> T:
        entity = await self.read(uuid)
        if entity is None or entity.is_deleted:
            raise KeyError(f"Entity with uuid {uuid} not found")
        clone = entity.model_copy(update={"uuid": uuid7()})
        return await self.create(clone)
