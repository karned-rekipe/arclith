from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager

from arclith.domain.ports.outbound.observability import TracePort, TraceSpan


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
