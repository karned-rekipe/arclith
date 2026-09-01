from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from urllib.parse import unquote

from arclith.domain.ports.outbound.observability import ContextPropagatorPort
from arclith.infrastructure.config import OpenTelemetryPropagationSettings


class OpenTelemetryContextPropagator(ContextPropagatorPort):
    def __init__(self, settings: OpenTelemetryPropagationSettings) -> None:
        self._settings = settings
        self._propagator = None

    def configure(self, settings: OpenTelemetryPropagationSettings) -> None:
        self._settings = settings
        self._propagator = None

    def extract(self, carrier: Mapping[str, str]) -> Mapping[str, str]:
        return _safe_carrier(carrier, self._settings)

    def inject(self, carrier: MutableMapping[str, str]) -> None:
        propagated: dict[str, str] = {}
        self._get_propagator().inject(propagated)
        for key in ("traceparent", "tracestate"):
            if value := propagated.get(key):
                carrier.setdefault(key, value)
        baggage = _filter_baggage(
            propagated.get("baggage", ""),
            allowlist=set(self._settings.baggage_allowlist),
            max_bytes=self._settings.max_baggage_bytes,
        )
        if baggage:
            carrier.setdefault("baggage", baggage)

    @contextmanager
    def context(self, carrier: Mapping[str, str] | None = None) -> Iterator[None]:
        from opentelemetry import context as otel_context

        safe_carrier = _safe_carrier(carrier or {}, self._settings)
        extracted = self._get_propagator().extract(safe_carrier)
        token = otel_context.attach(extracted)
        try:
            yield
        finally:
            otel_context.detach(token)

    def _get_propagator(self):
        if self._propagator is not None:
            return self._propagator
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        propagators = []
        if "tracecontext" in self._settings.propagators:
            propagators.append(TraceContextTextMapPropagator())
        if "baggage" in self._settings.propagators:
            propagators.append(W3CBaggagePropagator())
        self._propagator = CompositePropagator(propagators)
        return self._propagator


def _safe_carrier(
    carrier: Mapping[str, str], settings: OpenTelemetryPropagationSettings
) -> dict[str, str]:
    allowed: set[str] = set()
    if "tracecontext" in settings.propagators:
        allowed.update({"traceparent", "tracestate"})
    if "baggage" in settings.propagators:
        allowed.add("baggage")
    safe = {
        key.lower(): str(value)
        for key, value in carrier.items()
        if key.lower() in allowed
    }
    baggage = _filter_baggage(
        safe.get("baggage", ""),
        allowlist=set(settings.baggage_allowlist),
        max_bytes=settings.max_baggage_bytes,
    )
    if baggage:
        safe["baggage"] = baggage
    else:
        safe.pop("baggage", None)
    return safe


def _filter_baggage(raw: str, *, allowlist: set[str], max_bytes: int) -> str:
    if not raw or not allowlist:
        return ""
    kept: list[str] = []
    size = 0
    for member in raw.split(","):
        key, separator, _ = member.strip().partition("=")
        if not separator or unquote(key.strip()) not in allowlist:
            continue
        encoded = member.strip()
        encoded_size = len(encoded.encode("utf-8")) + (1 if kept else 0)
        if size + encoded_size > max_bytes:
            break
        kept.append(encoded)
        size += encoded_size
    return ",".join(kept)
