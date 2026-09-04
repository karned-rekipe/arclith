from __future__ import annotations

from typing import Any, TypeVar, cast

from arclith.adapters.outbound.relational.mapping import (
    RelationalEntityMapper,
    validate_relational_mapper,
)
from arclith.domain.models.entity import Entity

T = TypeVar("T", bound=Entity)


class RelationalMapperRegistry:
    """Exact entity-class registry for application-provided relational mappers."""

    def __init__(self) -> None:
        self._mappers: dict[type[Entity], RelationalEntityMapper[Any]] = {}

    def register(self, mapper: RelationalEntityMapper[T]) -> "RelationalMapperRegistry":
        validate_relational_mapper(mapper)
        entity_class = mapper.entity_class
        if entity_class in self._mappers:
            entity_path = _entity_path(entity_class)
            raise ValueError(
                f"A relational mapper is already registered for '{entity_path}'"
            )
        self._mappers[entity_class] = mapper
        return self

    def resolve(self, entity_class: type[T]) -> RelationalEntityMapper[T] | None:
        mapper = self._mappers.get(entity_class)
        return cast("RelationalEntityMapper[T] | None", mapper)

    def require(self, entity_class: type[T]) -> RelationalEntityMapper[T]:
        mapper = self.resolve(entity_class)
        if mapper is None:
            raise ValueError(
                "Structured relational mapping requires a registered mapper for "
                f"'{_entity_path(entity_class)}'"
            )
        return mapper


def _entity_path(entity_class: type[Entity]) -> str:
    return f"{entity_class.__module__}.{entity_class.__qualname__}"


__all__ = ["RelationalMapperRegistry"]
