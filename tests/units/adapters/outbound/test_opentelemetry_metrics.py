from __future__ import annotations

import logging
from typing import Any

from arclith.adapters.outbound.opentelemetry.logging import (
    OpenTelemetryLogRecordAdapter,
)
from arclith.adapters.outbound.opentelemetry.metrics import (
    OpenTelemetryMetricAdapter,
)


class RecordingInstrument:
    def __init__(self) -> None:
        self.calls: list[tuple[int | float, dict[str, Any]]] = []

    def add(self, value: int | float, attributes: dict[str, Any]) -> None:
        self.calls.append((value, attributes))

    def record(self, value: int | float, attributes: dict[str, Any]) -> None:
        self.calls.append((value, attributes))


class RecordingMeter:
    def __init__(self) -> None:
        self.counter = RecordingInstrument()
        self.histogram = RecordingInstrument()

    def create_counter(self, *args: Any, **kwargs: Any) -> RecordingInstrument:
        return self.counter

    def create_histogram(self, *args: Any, **kwargs: Any) -> RecordingInstrument:
        return self.histogram


class RecordingMeterProvider:
    def __init__(self) -> None:
        self.meter = RecordingMeter()

    def get_meter(self, *args: Any, **kwargs: Any) -> RecordingMeter:
        return self.meter


def test_metric_adapter_drops_high_cardinality_and_uuid_attributes() -> None:
    provider = RecordingMeterProvider()
    adapter = OpenTelemetryMetricAdapter(
        ensure_started=lambda: None,
        meter_provider=lambda: provider,
        enabled=lambda: True,
    )

    adapter.add_counter(
        "arclith.test",
        attributes={
            "operation": "read",
            "tenant.id": "customer-a",
            "entity": "550e8400-e29b-41d4-a716-446655440000",
            "huge": "x" * 129,
        },
    )

    assert provider.meter.counter.calls == [(1, {"operation": "read"})]


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_log_adapter_emits_explicit_record_without_sensitive_attributes() -> None:
    handler = RecordingHandler()
    adapter = OpenTelemetryLogRecordAdapter(
        ensure_started=lambda: None,
        handler=lambda: handler,
        enabled=lambda: True,
    )

    adapter.emit(
        "WARNING",
        "bounded message",
        attributes={
            "operation.name": "test",
            "authorization": "Bearer secret",
            "payload": "hidden",
        },
    )

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "bounded message"
    assert record.operation_name == "test"
    assert not hasattr(record, "authorization")
    assert not hasattr(record, "payload")
