from typing import Any
import pytest
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger, LogLevel


class DummyEntity(Entity):
    name: str = "test"


class NullLogger(Logger):
    def __init__(self) -> None:
        self.records: list[dict] = []

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        self.records.append({"level": level, "message": message, "metadata": metadata})


@pytest.fixture
def logger() -> NullLogger:
    return NullLogger()


@pytest.fixture
def repo() -> InMemoryRepository[DummyEntity]:
    return InMemoryRepository()

