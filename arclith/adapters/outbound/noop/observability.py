from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager

from typing import Any

from arclith.domain.ports.outbound.observability import (
    ContextPropagatorPort,
    CorrelationContextPort,
    LogRecordPort,
    MetricPort,
    ObservabilityRuntimePort,
    TracePort,
    TraceSpan,
)


class NoOpTraceSpan(TraceSpan):
    def set_outputs(self, outputs: object | None) -> None:
        return None

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        return None


class NoOpTraceAdapter(TracePort):
    """Zero-cost tracer used when no observability backend is selected."""

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        yield NoOpTraceSpan()

    @contextmanager
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        yield

    def inject(self, headers: MutableMapping[str, str]) -> None:
        return None

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None

    def diagnostics(self) -> Mapping[str, object]:
        return {"backend": "noop", "tracing": False}


class NoOpMetricAdapter(MetricPort):
    def add_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "1",
    ) -> None:
        return None

    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "ms",
    ) -> None:
        return None


class NoOpCorrelationContext(CorrelationContextPort):
    def current(self) -> Mapping[str, str | bool]:
        return {}

    def from_log_record(self, record: Any) -> Mapping[str, str | bool]:
        return {}


class NoOpContextPropagator(ContextPropagatorPort):
    def inject(self, carrier: MutableMapping[str, str]) -> None:
        return None

    @contextmanager
    def context(self, carrier: Mapping[str, str] | None = None) -> Iterator[None]:
        yield


class NoOpLogRecordAdapter(LogRecordPort):
    def emit(
        self,
        level: str,
        body: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        return None


class NoOpObservabilityRuntime(ObservabilityRuntimePort):
    """No-op runtime used when no observability capability is activated."""

    def __init__(self) -> None:
        self._tracer = NoOpTraceAdapter()
        self._metrics = NoOpMetricAdapter()
        self._correlation = NoOpCorrelationContext()
        self._propagator = NoOpContextPropagator()
        self._logs = NoOpLogRecordAdapter()

    @property
    def tracer(self) -> TracePort:
        return self._tracer

    @property
    def metrics(self) -> MetricPort:
        return self._metrics

    @property
    def correlation(self) -> CorrelationContextPort:
        return self._correlation

    @property
    def propagator(self) -> ContextPropagatorPort:
        return self._propagator

    @property
    def logs(self) -> LogRecordPort:
        return self._logs

    def start(self) -> None:
        return None

    def instrument_fastapi(self, app: Any) -> None:
        return None

    def force_flush(self, timeout: float | None = None) -> bool:
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        return None

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "backend": "noop",
            "started": False,
            "signals": {"traces": False, "metrics": False, "logs": False},
        }
