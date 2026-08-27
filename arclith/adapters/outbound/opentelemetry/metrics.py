from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from arclith.domain.ports.outbound.observability import MetricPort

_HIGH_CARDINALITY_KEY = re.compile(
    r"(^|[._-])(body|content|email|id|payload|prompt|query|secret|tenant|text|token|user|uuid)([._-]|$)",
    re.IGNORECASE,
)
_UUID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class OpenTelemetryMetricAdapter(MetricPort):
    def __init__(
        self,
        *,
        ensure_started: Callable[[], None],
        meter_provider: Callable[[], Any],
        enabled: Callable[[], bool],
    ) -> None:
        self._ensure_started = ensure_started
        self._meter_provider = meter_provider
        self._enabled = enabled
        self._counters: dict[tuple[str, str, str], Any] = {}
        self._histograms: dict[tuple[str, str, str], Any] = {}

    def add_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "1",
    ) -> None:
        self._ensure_started()
        if not self._enabled():
            return
        key = (name, description, unit)
        instrument = self._counters.get(key)
        if instrument is None:
            meter = self._meter_provider().get_meter("arclith", "1")
            instrument = meter.create_counter(name, description=description, unit=unit)
            self._counters[key] = instrument
        instrument.add(value, _bounded_metric_attributes(attributes or {}))

    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "ms",
    ) -> None:
        self._ensure_started()
        if not self._enabled():
            return
        key = (name, description, unit)
        instrument = self._histograms.get(key)
        if instrument is None:
            meter = self._meter_provider().get_meter("arclith", "1")
            instrument = meter.create_histogram(
                name, description=description, unit=unit
            )
            self._histograms[key] = instrument
        instrument.record(value, _bounded_metric_attributes(attributes or {}))


def _bounded_metric_attributes(
    attributes: Mapping[str, str | bool | int | float],
) -> dict[str, str | bool | int | float]:
    bounded: dict[str, str | bool | int | float] = {}
    for raw_key, value in attributes.items():
        key = str(raw_key)[:128]
        if _HIGH_CARDINALITY_KEY.search(key):
            continue
        if isinstance(value, str):
            if len(value) > 128 or _UUID_VALUE.match(value):
                continue
            bounded[key] = value
        elif isinstance(value, (bool, int, float)):
            bounded[key] = value
    return bounded
