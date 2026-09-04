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
from arclith.adapters.outbound.relational.mapping import (
    RelationalColumn,
    RelationalEntityMapper,
    validate_relational_mapper,
)
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
    boolean: Any
    column: Any
    date: Any
    datetime: Any
    float_: Any
    index: Any
    integer: Any
    jsonb: Any
    metadata: Any
    string: Any
    table: Any
    uuid: Any
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
            Boolean,
            Column,
            Date,
            DateTime,
            Float,
            Index,
            Integer,
            MetaData,
            String,
            Table,
            Uuid,
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
        boolean=Boolean,
        column=Column,
        date=Date,
        datetime=DateTime,
        float_=Float,
        index=Index,
        integer=Integer,
        jsonb=JSONB,
        metadata=MetaData,
        string=String,
        table=Table,
        uuid=Uuid,
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
    """PostgreSQL repository using generic JSONB or an explicit typed mapper."""

    def __init__(
        self,
        config: PostgreSQLConfig,
        entity_class: type[T],
        logger: Logger,
        *,
        mapper: RelationalEntityMapper[T] | None = None,
    ) -> None:
        if config.mapping_strategy == "structured" and mapper is None:
            raise ValueError(
                "PostgreSQL structured mapping requires an explicit relational mapper"
            )
        if config.mapping_strategy == "generic_json" and mapper is not None:
            raise ValueError(
                "A relational mapper requires mapping_strategy='structured'"
            )
        if mapper is not None:
            validate_relational_mapper(mapper)
            if mapper.entity_class is not entity_class:
                raise ValueError(
                    "Relational mapper entity_class does not match the repository entity"
                )
        self._config = config
        self._entity_class = entity_class
        self._logger = logger
        self._mapper = mapper
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
        return f"{config.schema}.{self._table_name(config)}"

    def _table_name(self, config: PostgreSQLConfig) -> str:
        base_name = (
            self._mapper.table_name
            if self._mapper is not None
            else self._entity_class.__name__.lower()
        )
        return f"{config.table_prefix}{base_name}"

    def _table_for(self, config: PostgreSQLConfig) -> tuple[Any, Any]:
        table_key = self._table_key(config)
        if table_key not in self._tables:
            self._tables[table_key] = self._build_table(config)
        return self._tables[table_key]

    def _build_table(self, config: PostgreSQLConfig) -> tuple[Any, Any]:
        table_name = self._table_name(config)
        if not _IDENTIFIER_RE.fullmatch(table_name):
            raise ValueError(f"Invalid PostgreSQL table name: {table_name}")

        api = _sqlalchemy_api()
        metadata = api.metadata(schema=config.schema)
        if self._mapper is not None:
            table = api.table(
                table_name,
                metadata,
                *(
                    api.column(
                        column.name,
                        self._column_type(api, column),
                        nullable=column.nullable,
                        primary_key=column.primary_key,
                        index=column.indexed,
                        unique=column.unique,
                    )
                    for column in self._mapper.columns
                ),
            )
            for index in self._mapper.indexes:
                api.index(
                    index.name,
                    *(table.c[name] for name in index.columns),
                    unique=index.unique,
                )
            return metadata, table

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

    @staticmethod
    def _column_type(api: _SQLAlchemyAPI, column: RelationalColumn) -> Any:
        types = {
            "boolean": api.boolean,
            "date": api.date,
            "datetime": lambda: api.datetime(timezone=True),
            "float": api.float_,
            "integer": api.integer,
            "json": api.jsonb,
            "string": api.string,
            "uuid": lambda: api.uuid(as_uuid=True),
        }
        column_type = types[column.kind]
        return column_type() if callable(column_type) else column_type

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
        if config.auto_create_schema:
            await self._ensure_schema(engine, url, metadata, self._table_key(config))
        return engine, table

    def _entity_values(self, entity: T) -> dict[str, Any]:
        if self._mapper is not None:
            values = dict(self._mapper.to_record(entity))
            expected = {column.name for column in self._mapper.columns}
            actual = set(values)
            missing = sorted(expected - actual)
            unknown = sorted(actual - expected)
            if missing or unknown:
                details = []
                if missing:
                    details.append(f"missing: {', '.join(missing)}")
                if unknown:
                    details.append(f"unknown: {', '.join(unknown)}")
                raise ValueError(
                    "Structured relational record does not match declared columns "
                    f"({'; '.join(details)})"
                )
            if values["uuid"] != entity.uuid:
                raise ValueError(
                    "Structured relational record uuid must match the entity uuid"
                )
            return values
        return {
            "uuid": str(entity.uuid),
            "data": entity.model_dump(mode="json"),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def _row_to_entity(self, row: Any) -> T:
        if self._mapper is not None:
            record = {
                column.name: row[column.name] for column in self._mapper.columns
            }
            entity = self._mapper.from_record(record)
            if not isinstance(entity, self._entity_class):
                raise ValueError(
                    "Relational mapper from_record() returned an unexpected entity type"
                )
            return entity
        payload = row["data"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("PostgreSQL repository row payload must be a JSON object")
        return self._entity_class(**payload)

    def _uuid_value(self, uuid: UUID) -> UUID | str:
        return uuid if self._mapper is not None else str(uuid)

    def _entity_selection(self, table: Any) -> Any:
        return table if self._mapper is not None else table.c.data

    async def create(self, entity: T) -> T:
        engine, table = await self._engine_and_table()
        async with engine.begin() as connection:
            await connection.execute(
                _sqlalchemy_api().insert(table).values(**self._entity_values(entity))
            )
        return entity

    async def read(self, uuid: UUID) -> T | None:
        engine, table = await self._engine_and_table()
        statement = _sqlalchemy_api().select(self._entity_selection(table)).where(
            table.c.uuid == self._uuid_value(uuid)
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
            .where(table.c.uuid == self._uuid_value(entity.uuid))
            .values(**values)
        )
        async with engine.begin() as connection:
            await connection.execute(statement)
        return entity

    async def delete(self, uuid: UUID) -> None:
        engine, table = await self._engine_and_table()
        statement = _sqlalchemy_api().delete(table).where(
            table.c.uuid == self._uuid_value(uuid)
        )
        async with engine.begin() as connection:
            await connection.execute(statement)

    async def find_all(self) -> list[T]:
        engine, table = await self._engine_and_table()
        statement = (
            _sqlalchemy_api()
            .select(self._entity_selection(table))
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
            .select(
                self._entity_selection(table),
                _sqlalchemy_api().count().over().label("__total"),
            )
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
            .select(self._entity_selection(table))
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
