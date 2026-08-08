from datetime import date, datetime, timezone
from typing import Any

from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.adapters.outbound.mongodb.repository import MongoDBRepository
from arclith.domain.models.entity import Entity
from pydantic import Field


class Item(Entity):
    due_on: date
    metadata: dict[str, Any] = Field(default_factory=dict)


def test_to_doc_serializes_date_and_datetime(logger) -> None:
    repository = MongoDBRepository(MongoDBConfig(db_name="demo"), Item, logger)
    completed_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    item = Item(
        due_on=date(2026, 9, 1),
        metadata={"completed_at": completed_at, "milestones": [date(2026, 9, 2)]},
    )

    doc = repository._to_doc(item)

    assert doc["due_on"] == "2026-09-01"
    assert doc["metadata"]["completed_at"] == completed_at.isoformat()
    assert doc["metadata"]["milestones"] == ["2026-09-02"]
