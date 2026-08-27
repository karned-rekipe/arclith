from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from arclith.adapters.outbound.noop.observability import NoOpTraceSpan
from arclith.domain.ports.outbound.observability import (
    ContextPropagatorPort,
    TracePort,
    TraceSpan,
)
from arclith.infrastructure.config import OpenTelemetryCaptureSettings

_SENSITIVE_FRAGMENTS = frozenset(
    {
        "authorization",
        "body",
        "content",
        "cookie",
        "db.statement",
        "document",
        "email",
        "header",
        "password",
        "payload",
        "prompt",
        "query",
        "response",
        "secret",
        "tenant",
        "token",
        "tool.arguments",
        "tool.result",
        "user",
        "uuid",
    }
)


class OpenTelemetryTraceSpan(TraceSpan):
    def __init__(self, span: Any, capture: OpenTelemetryCaptureSettings) -> None:
        self._span = span
        self._capture = capture

    def set_outputs(self, outputs: object | None) -> None:
        if isinstance(outputs, Mapping):
            safe = {
                f"arclith.output.{key}": value
                for key, value in outputs.items()
                if key == "status" or self._capture.tool_content
            }
            self._span.set_attributes(_safe_trace_attributes(safe))

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        self._span.set_attributes(_safe_trace_attributes(metadata))

    def record_exception(self, error: BaseException) -> None:
        self._span.record_exception(error)

    def set_status(self, status: str, description: str | None = None) -> None:
        from opentelemetry.trace import Status, StatusCode

        code = StatusCode.ERROR if status.lower() == "error" else StatusCode.OK
        self._span.set_status(Status(code, description))


class OpenTelemetryTraceAdapter(TracePort):
    def __init__(
        self,
        *,
        ensure_started: Callable[[], None],
        tracer_provider: Callable[[], Any],
        propagator: ContextPropagatorPort,
        capture: OpenTelemetryCaptureSettings,
        enabled: Callable[[], bool],
        flush: Callable[[float | None], bool],
        shutdown: Callable[[float | None], None],
        diagnostics: Callable[[], Mapping[str, Any]],
    ) -> None:
        self._ensure_started = ensure_started
        self._tracer_provider = tracer_provider
        self._propagator = propagator
        self._capture = capture
        self._enabled = enabled
        self._flush = flush
        self._shutdown = shutdown
        self._diagnostics = diagnostics
        self._enabled_override: ContextVar[bool | None] = ContextVar(
            "arclith_opentelemetry_enabled", default=None
        )

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
        override = self._enabled_override.get()
        if override is False:
            yield NoOpTraceSpan()
            return
        self._ensure_started()
        if not self._enabled():
            yield NoOpTraceSpan()
            return
        from opentelemetry.trace import SpanKind

        span_kind = {
            "server": SpanKind.SERVER,
            "client": SpanKind.CLIENT,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
        }.get(kind, SpanKind.INTERNAL)
        tracer = self._tracer_provider().get_tracer("arclith", "1")
        attributes = _safe_trace_attributes(metadata or {})
        if tags:
            attributes["arclith.tags"] = tuple(str(tag)[:64] for tag in tags[:16])
        with tracer.start_as_current_span(
            name,
            kind=span_kind,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as native_span:
            span = OpenTelemetryTraceSpan(native_span, self._capture)
            try:
                yield span
            except BaseException as exc:
                span.record_exception(exc)
                span.set_status("error", type(exc).__name__)
                raise

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
        token = self._enabled_override.set(enabled)
        try:
            self._ensure_started()
            if self._enabled() and enabled is not False:
                with self._propagator.context(parent):
                    yield
            else:
                yield
        finally:
            self._enabled_override.reset(token)

    def inject(self, headers: MutableMapping[str, str]) -> None:
        self._ensure_started()
        if not self._enabled():
            return
        self._propagator.inject(headers)

    def flush(self, timeout: float | None = None) -> None:
        self._flush(timeout)

    def close(self, timeout: float | None = None) -> None:
        self._shutdown(timeout)

    def diagnostics(self) -> Mapping[str, Any]:
        return self._diagnostics()


def _safe_trace_attributes(
    metadata: Mapping[str, object],
) -> dict[str, str | bool | int | float | Sequence[str]]:
    safe: dict[str, str | bool | int | float | Sequence[str]] = {}
    for raw_key, value in metadata.items():
        key = str(raw_key)[:128]
        lowered = key.lower()
        if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
            continue
        if isinstance(value, (str, bool, int, float)):
            safe[key] = value[:512] if isinstance(value, str) else value
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = [str(item)[:128] for item in value[:32]]
            safe[key] = values
    return safe
