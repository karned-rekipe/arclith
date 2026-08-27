from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Callable, ContextManager

TraceAnonymizer = Callable[[dict[str, Any]], dict[str, Any]]


class TraceSpan(ABC):
    """Provider-neutral handle for a span created at an application boundary."""

    @abstractmethod
    def set_outputs(self, outputs: object | None) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        raise NotImplementedError  # pragma: no cover

    def record_exception(self, error: BaseException) -> None:
        """Record an exception when the selected backend supports it."""

    def set_status(self, status: str, description: str | None = None) -> None:
        """Set a provider-neutral span status when supported."""


class TracePort(ABC):
    """Outbound tracing contract with a no-op implementation available by default."""

    @abstractmethod
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> ContextManager[TraceSpan]:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> ContextManager[None]:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def inject(self, headers: MutableMapping[str, str]) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def flush(self, timeout: float | None = None) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def close(self, timeout: float | None = None) -> None:
        raise NotImplementedError  # pragma: no cover

    def diagnostics(self) -> Mapping[str, Any]:
        return {}


class MetricPort(ABC):
    """Provider-neutral metrics API restricted to bounded attributes."""

    @abstractmethod
    def add_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "1",
    ) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "ms",
    ) -> None:
        raise NotImplementedError  # pragma: no cover


class CorrelationContextPort(ABC):
    """Expose trace correlation without leaking a telemetry SDK into callers."""

    @abstractmethod
    def current(self) -> Mapping[str, str | bool]:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def from_log_record(self, record: Any) -> Mapping[str, str | bool]:
        raise NotImplementedError  # pragma: no cover


class ContextPropagatorPort(ABC):
    """Inject and attach distributed context for transport adapters."""

    @abstractmethod
    def inject(self, carrier: MutableMapping[str, str]) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def context(self, carrier: Mapping[str, str] | None = None) -> ContextManager[None]:
        raise NotImplementedError  # pragma: no cover


class LogRecordPort(ABC):
    """Optional structured log export kept separate from local logging."""

    @abstractmethod
    def emit(
        self,
        level: str,
        body: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        raise NotImplementedError  # pragma: no cover


class ObservabilityRuntimePort(ABC):
    """Lifecycle and composition contract owned by the Arclith bootstrap."""

    @property
    @abstractmethod
    def tracer(self) -> TracePort:
        raise NotImplementedError  # pragma: no cover

    @property
    @abstractmethod
    def metrics(self) -> MetricPort:
        raise NotImplementedError  # pragma: no cover

    @property
    @abstractmethod
    def correlation(self) -> CorrelationContextPort:
        raise NotImplementedError  # pragma: no cover

    @property
    @abstractmethod
    def propagator(self) -> ContextPropagatorPort:
        raise NotImplementedError  # pragma: no cover

    @property
    @abstractmethod
    def logs(self) -> LogRecordPort:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def instrument_fastapi(self, app: Any) -> None:
        raise NotImplementedError  # pragma: no cover

    def pydantic_ai_instrumentation(self) -> Any | None:
        return None

    def instrument_langgraph(self, graph: Any, *, name: str) -> Any:
        """Instrument a compiled graph when the backend supports it."""

        return graph

    @abstractmethod
    def force_flush(self, timeout: float | None = None) -> bool:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def shutdown(self, timeout: float | None = None) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def diagnostics(self) -> Mapping[str, Any]:
        raise NotImplementedError  # pragma: no cover

    def native_providers(self) -> Mapping[str, Any]:
        """Explicit vendor-specific escape hatch for advanced integrations."""

        return {}
