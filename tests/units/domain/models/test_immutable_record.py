from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arclith.domain.models.immutable_record import ImmutableRecord


class Measurement(ImmutableRecord):
    value: float


def test_immutable_record_has_uuid7_and_normalizes_timestamps_to_utc() -> None:
    occurred_at = datetime(2026, 9, 13, 14, 30, tzinfo=timezone(timedelta(hours=2)))

    record = Measurement(occurred_at=occurred_at, value=12.5)

    assert record.uuid.version == 7
    assert record.occurred_at == datetime(2026, 9, 13, 12, 30, tzinfo=UTC)
    assert record.occurred_at.tzinfo is UTC
    assert record.recorded_at is None


def test_immutable_record_refuses_attribute_mutation() -> None:
    record = Measurement(
        occurred_at=datetime(2026, 9, 13, 12, 30, tzinfo=UTC),
        value=12.5,
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        record.value = 13.0


def test_immutable_record_json_round_trip_is_stable() -> None:
    record = Measurement(
        occurred_at=datetime(2026, 9, 13, 12, 30, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 13, 12, 31, tzinfo=UTC),
        value=12.5,
    )

    restored = Measurement.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.model_dump_json() == record.model_dump_json()


def test_immutable_record_requires_an_aware_occurred_at() -> None:
    with pytest.raises(ValidationError, match="timezone_aware"):
        Measurement(
            occurred_at=datetime(2026, 9, 13, 12, 30),
            value=12.5,
        )


@pytest.mark.parametrize(
    "data",
    [
        {"value": 1.0},
        {"value": 1.0, "occurred_at": "2026-09-13T12:30:00Z", "uuid": "bad"},
        {
            "value": 1.0,
            "occurred_at": "2026-09-13T12:30:00Z",
            "recorded_at": "2026-09-13",
        },
    ],
)
def test_invalid_record_input_is_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Measurement.model_validate(data)
