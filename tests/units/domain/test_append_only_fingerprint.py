from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer

from arclith.domain.models.immutable_record import ImmutableRecord
from arclith.domain.ports.outbound.append_only_store import AppendOnlyError
from arclith.domain.services.append_only import record_fingerprint


class Fact(ImmutableRecord):
    payload: Any


def fact(payload: object) -> Fact:
    return Fact(
        uuid=UUID("01951234-5678-7abc-8ef0-123456789abc"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def test_fingerprint_includes_excluded_and_custom_serialized_fields() -> None:
    class PrivateFact(ImmutableRecord):
        private: str = Field(exclude=True)
        display: str

        @field_serializer("display")
        def mask(self, value: str) -> str:
            return "masked"

    original = PrivateFact(
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC), private="A", display="A"
    )
    for name in ("private", "display"):
        changed = original.model_copy(update={name: "B"})
        assert original.model_dump() == changed.model_dump()
        assert record_fingerprint(original) != record_fingerprint(changed)


def test_canonical_nested_models_and_supported_scalar_types() -> None:
    class Unit(StrEnum):
        CELSIUS = "C"

    class Nested(BaseModel):
        model_config = ConfigDict(extra="allow")
        hidden: int = Field(exclude=True)

    value = {
        "unit": Unit.CELSIUS,
        "amount": Decimal("1.25"),
        "date": date(2026, 1, 1),
        "uuid": UUID(int=1),
        "flags": (True, None, 1, 1.5),
        "nested": Nested(hidden=1, extra="yes"),
    }
    expected = {
        "nested": {"hidden": 1, "extra": "yes"},
        "flags": [True, None, 1, 1.5],
        "uuid": str(UUID(int=1)),
        "date": "2026-01-01",
        "amount": "1.25",
        "unit": "C",
    }
    assert record_fingerprint(fact(value)) == record_fingerprint(fact(expected))


def test_utc_equivalent_business_datetimes_have_the_same_fingerprint() -> None:
    utc = datetime(2026, 1, 1, tzinfo=UTC)
    offset = utc.astimezone(timezone(timedelta(hours=2)))
    assert record_fingerprint(fact(utc)) == record_fingerprint(fact(offset))


@pytest.mark.parametrize(
    "payload",
    [
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        {1: "value"},
        {"unordered"},
        SecretStr("never-print-this"),
        b"binary",
        datetime(2026, 1, 1),
    ],
)
def test_unsupported_content_is_rejected_without_leaking_values(
    payload: object,
) -> None:
    with pytest.raises(AppendOnlyError) as caught:
        record_fingerprint(fact(payload))
    assert "never-print-this" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_cyclic_payload_is_rejected_with_a_bounded_error() -> None:
    payload: list[Any] = []
    payload.append(payload)
    with pytest.raises(AppendOnlyError, match="nesting limit"):
        record_fingerprint(fact(payload))


def test_optional_extra_fields_are_included_in_the_fingerprint() -> None:
    class ExtendedFact(Fact):
        model_config = ConfigDict(extra="allow")

    original = ExtendedFact(**fact(None).model_dump(), source="one")
    changed = original.model_copy(update={"source": "two"})
    assert record_fingerprint(original) != record_fingerprint(changed)
