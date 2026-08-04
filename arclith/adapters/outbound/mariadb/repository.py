from asyncio import Lock
import json
import re
from typing import Any, Generic, TypeVar

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from uuid6 import UUID, uuid7

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.mariadb.config import MariaDBConfig
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MariaDBRepository(Repository[T], Generic[T]):
    """Generic MariaDB repository storing each entity as JSON behind Repository[T]."""

    def __init__(self, config: MariaDBConfig, entity_class: type[T], logger: Logger) -> None:
        self._config = config
        self._entity_class = entity_class
        self._logger = logger
        self._metadata = MetaData()
        self._table = self._build_table(config.table_prefix, entity_class)
        self._engines: dict[str, AsyncEngine] = {}
        self._ready_urls: set[str] = set()
        self._schema_locks: dict[str, Lock] = {}

    def _build_table(self, table_prefix: str, entity_class: type[T]) -> Table:
        table_name = f"{table_prefix}{entity_class.__name__.lower()}"
        if not _IDENTIFIER_RE.match(table_name):
            raise ValueError(f"Invalid MariaDB table name: {table_name}")

        return Table(
            table_name,
            self._metadata,
            Column("uuid", String(36), primary_key=True),
            Column("data", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("deleted_at", DateTime(timezone=True), nullable=True),
            Column("version", Integer, nullable=False),
        )

    def _active_config(self) -> MariaDBConfig:
        coords = get_adapter_tenant_context("mariadb")
        if coords is None:
            return self._config
        return self._config.with_tenant_params(coords.params)

    def _engine_for(self, url: str) -> AsyncEngine:
        if url not in self._engines:
            self._engines[url] = create_async_engine(url, pool_pre_ping=True)
            self._logger.debug("MariaDB engine created", table=self._table.name)
        return self._engines[url]

    def _schema_lock_for(self, url: str) -> Lock:
        if url not in self._schema_locks:
            self._schema_locks[url] = Lock()
        return self._schema_locks[url]

    async def _ensure_schema(self, engine: AsyncEngine, url: str) -> None:
        if url in self._ready_urls:
            return

        async with self._schema_lock_for(url):
            if url in self._ready_urls:
                return
            async with engine.begin() as connection:
                await connection.run_sync(self._metadata.create_all)
            self._ready_urls.add(url)

    async def _engine(self) -> AsyncEngine:
        url = self._active_config().connection_url()
        engine = self._engine_for(url)
        await self._ensure_schema(engine, url)
        return engine

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
            raise ValueError("MariaDB repository row payload must be a JSON object")
        return self._entity_class(**payload)

    async def create(self, entity: T) -> T:
        engine = await self._engine()
        async with engine.begin() as connection:
            await connection.execute(insert(self._table).values(**self._entity_values(entity)))
        return entity

    async def read(self, uuid: UUID) -> T | None:
        engine = await self._engine()
        statement = select(self._table.c.data).where(self._table.c.uuid == str(uuid))
        async with engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().first()
        return self._row_to_entity(row) if row is not None else None

    async def update(self, entity: T) -> T:
        engine = await self._engine()
        values = self._entity_values(entity)
        values.pop("uuid")
        statement = update(self._table).where(self._table.c.uuid == str(entity.uuid)).values(**values)
        async with engine.begin() as connection:
            await connection.execute(statement)
        return entity

    async def delete(self, uuid: UUID) -> None:
        engine = await self._engine()
        statement = delete(self._table).where(self._table.c.uuid == str(uuid))
        async with engine.begin() as connection:
            await connection.execute(statement)

    async def find_all(self) -> list[T]:
        engine = await self._engine()
        statement = (
            select(self._table.c.data)
            .where(self._table.c.deleted_at.is_(None))
            .order_by(self._table.c.created_at, self._table.c.uuid)
        )
        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [self._row_to_entity(row) for row in rows]

    async def find_page(self, offset: int = 0, limit: int | None = None) -> tuple[list[T], int]:
        engine = await self._engine()
        statement = (
            select(self._table.c.data, func.count().over().label("__total"))
            .where(self._table.c.deleted_at.is_(None))
            .order_by(self._table.c.created_at, self._table.c.uuid)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)

        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()

        total = int(rows[0]["__total"]) if rows else 0
        return [self._row_to_entity(row) for row in rows], total

    async def find_deleted(self) -> list[T]:
        engine = await self._engine()
        statement = (
            select(self._table.c.data)
            .where(self._table.c.deleted_at.is_not(None))
            .order_by(self._table.c.deleted_at, self._table.c.uuid)
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
