from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from typing import Any, Generic, Optional, TypeVar
from uuid6 import UUID, uuid7

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound = Entity)


class _MongoCollection:
    # Cache de clients par URI pour réutiliser le pool de connexions Motor
    _clients: dict[str, AsyncIOMotorClient] = {}

    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        self._config = config
        self._logger = logger
        self._client: AsyncIOMotorClient | None = None

    async def __aenter__(self) -> AsyncIOMotorCollection:
        coords = get_adapter_tenant_context("mongodb")
        effective_uri = (coords.get("uri") if coords else None) or self._config.uri
        effective_db = (coords.get("db_name") if coords else None) or self._config.db_name
        if not effective_uri:
            raise ValueError("Aucune URI MongoDB : configurez uri ou activez le mode multitenant")

        if effective_uri in self._clients:
            self._client = self._clients[effective_uri]
        else:
            self._client = AsyncIOMotorClient(effective_uri)
            self._clients[effective_uri] = self._client
            self._logger.debug(
                "🔌 MongoDB client created",
                db=effective_db,
                collection=self._config.collection_name,
            )

        self._logger.debug(
            "🔌 MongoDB collection acquired",
            db=effective_db,
            collection=self._config.collection_name,
        )
        return self._client[effective_db][self._config.collection_name]  # type: ignore[return-value, index]

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Ne ferme plus le client ici pour conserver le pool Motor.
        self._logger.debug(
            "🔌 MongoDB collection released",
            db=self._config.db_name,
            collection=self._config.collection_name,
        )


class MongoDBRepository(Repository[T], Generic[T]):
    def __init__(self, config: MongoDBConfig, entity_class: type[T], logger: Logger) -> None:
        resolved_name = config.collection_name or entity_class.__name__.lower()
        self._config = MongoDBConfig(uri=config.uri, db_name=config.db_name, collection_name=resolved_name)
        self._entity_class = entity_class
        self._logger = logger

    def _collection(self) -> _MongoCollection:
        return _MongoCollection(self._config, self._logger)

    def _to_doc(self, entity: T) -> dict[str, Any]:
        doc = entity.model_dump()
        doc["_id"] = str(doc.pop("uuid"))
        for key, value in doc.items():
            if isinstance(value, datetime):
                doc[key] = value.isoformat()
        return doc

    def _from_doc(self, doc: dict[str, Any]) -> T:
        doc = dict(doc)
        doc["uuid"] = UUID(doc.pop("_id"))
        entity_fields = set(self._entity_class.model_fields.keys())
        datetime_fields = {"created_at", "updated_at", "deleted_at"}
        for key in list(doc.keys()):
            if key not in entity_fields:
                doc.pop(key)
            elif isinstance(doc[key], str) and key in datetime_fields:
                try:
                    doc[key] = datetime.fromisoformat(doc[key])
                except ValueError:
                    self._logger.warning(
                        f"Failed to parse field '{key}' as datetime from value {doc[key]!r}; leaving as string."
                    )
        return self._entity_class(**doc)

    async def create(self, entity: T) -> T:
        async with self._collection() as col:
            await col.insert_one(self._to_doc(entity))
        return entity

    async def read(self, uuid: UUID) -> Optional[T]:
        async with self._collection() as col:
            doc = await col.find_one({"_id": str(uuid)})
        return self._from_doc(doc) if doc else None

    async def update(self, entity: T) -> T:
        async with self._collection() as col:
            await col.replace_one({"_id": str(entity.uuid)}, self._to_doc(entity))
        return entity

    async def delete(self, uuid: UUID) -> None:
        async with self._collection() as col:
            await col.delete_one({"_id": str(uuid)})

    async def find_all(self) -> list[T]:
        async with self._collection() as col:
            return [self._from_doc(doc) async for doc in col.find({"deleted_at": None})]

    async def find_page(self, offset: int = 0, limit: int | None = None) -> tuple[list[T], int]:
        """Single-query pagination via MongoDB $facet aggregation."""
        from typing import Any, cast
        from collections.abc import Mapping, Sequence
        
        data_pipeline: list[dict] = [{"$skip": offset}]
        if limit is not None:
            data_pipeline.append({"$limit": limit})
        pipeline: Sequence[Mapping[str, Any]] = cast(
            Sequence[Mapping[str, Any]],
            [
                {"$match": {"deleted_at": None}},
                {"$facet": {
                    "data": data_pipeline,
                    "total": [{"$count": "count"}],
                }},
            ]
        )
        async with self._collection() as col:
            result = await col.aggregate(pipeline).to_list(length=1)
        if not result:
            return [], 0
        facet = result[0]
        items = [self._from_doc(doc) for doc in facet.get("data", [])]
        total = facet["total"][0]["count"] if facet.get("total") else 0
        return items, total

    async def find_deleted(self) -> list[T]:
        async with self._collection() as col:
            return [self._from_doc(doc) async for doc in col.find({"deleted_at": {"$ne": None}})]

    async def duplicate(self, uuid: UUID) -> T:
        async with self._collection() as col:
            doc = await col.find_one({"_id": str(uuid), "deleted_at": None})
            if doc is None:
                raise KeyError(f"Entity with uuid {uuid} not found")
            clone = self._from_doc({**doc}).model_copy(update={"uuid": uuid7()})
            await col.insert_one(self._to_doc(clone))
        return clone
