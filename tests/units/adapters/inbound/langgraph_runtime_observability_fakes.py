from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from arclith.adapters.inbound.langgraph_runtime import (
    InMemoryRunCoordinator,
    InMemoryRuntimeCatalog,
    LangGraphRuntime,
)
from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.domain.ports.outbound.observability import (
    ContextPropagatorPort,
    TracePort,
    TraceSpan,
)


class RecordingSpan(TraceSpan):
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self._events = events

    def set_outputs(self, outputs: object | None) -> None:
        self._events.append(("span.outputs", outputs))

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        self._events.append(("span.metadata", dict(metadata)))

    def record_exception(self, error: BaseException) -> None:
        self._events.append(("span.exception", type(error).__name__))

    def set_status(self, status: str, description: str | None = None) -> None:
        self._events.append(("span.status", (status, description)))


class RecordingPropagator(ContextPropagatorPort):
    def __init__(
        self,
        events: list[tuple[str, Any]],
        current: ContextVar[Mapping[str, str] | None],
    ) -> None:
        self._events = events
        self._current = current

    def extract(self, carrier: Mapping[str, str]) -> Mapping[str, str]:
        normalized = {str(key).lower(): str(value) for key, value in carrier.items()}
        safe = {
            key: normalized[key]
            for key in ("langsmith-trace", "traceparent", "tracestate")
            if normalized.get(key)
        }
        baggage = ",".join(
            member.strip()
            for member in normalized.get("baggage", "").split(",")
            if member.strip().partition("=")[0] == "safe"
        )
        if baggage:
            safe["baggage"] = baggage
        self._events.append(("extract", safe))
        return safe

    def inject(self, carrier: MutableMapping[str, str]) -> None:
        carrier.update(self._current.get() or {})

    @contextmanager
    def context(self, carrier: Mapping[str, str] | None = None) -> Iterator[None]:
        safe = self.extract(carrier or {})
        token = self._current.set(safe)
        self._events.append(("context.enter", safe))
        try:
            yield
        finally:
            self._events.append(("context.exit", safe))
            self._current.reset(token)


class RecordingTracer(TracePort):
    def __init__(
        self,
        events: list[tuple[str, Any]],
        current: ContextVar[Mapping[str, str] | None],
    ) -> None:
        self._events = events
        self._current = current

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
        self._events.append(
            (
                "span.enter",
                {
                    "name": name,
                    "kind": kind,
                    "inputs": inputs,
                    "tags": tuple(tags),
                    "metadata": dict(metadata or {}),
                    "parent": dict(self._current.get() or {}),
                },
            )
        )
        span = RecordingSpan(self._events)
        try:
            yield span
        except BaseException as error:
            span.record_exception(error)
            span.set_status("error", type(error).__name__)
            raise
        finally:
            self._events.append(("span.exit", name))

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
        token = self._current.set(parent)
        try:
            yield
        finally:
            self._current.reset(token)

    def inject(self, headers: MutableMapping[str, str]) -> None:
        headers.update(self._current.get() or {})

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None


class RecordingObservability(NoOpObservabilityRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, Any]] = []
        self.current: ContextVar[Mapping[str, str] | None] = ContextVar(
            "runtime_test_trace_context",
            default=None,
        )
        self._recording_propagator = RecordingPropagator(self.events, self.current)
        self._recording_tracer = RecordingTracer(self.events, self.current)

    @property
    def propagator(self) -> ContextPropagatorPort:
        return self._recording_propagator

    @property
    def tracer(self) -> TracePort:
        return self._recording_tracer


class RecordingGraph:
    def __init__(
        self,
        current: ContextVar[Mapping[str, str] | None],
        *,
        delay: float = 0,
        fail: bool = False,
    ) -> None:
        self._current = current
        self._delay = delay
        self._fail = fail
        self.parents: list[dict[str, str]] = []

    async def ainvoke(self, value: Any, config: Any) -> Any:
        self.parents.append(dict(self._current.get() or {}))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise ValueError("graph failed")
        return {"status": "ok"}

    async def astream(self, value: Any, config: Any, **kwargs: Any) -> Any:
        self.parents.append(dict(self._current.get() or {}))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise ValueError("graph failed")
        yield {"status": "ok"}

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(config={"configurable": {}}, values={"status": "ok"})


def build_runtime(
    observability: RecordingObservability,
    graph: RecordingGraph,
) -> LangGraphRuntime:
    return LangGraphRuntime(
        {"test_agent": graph},
        InMemoryRuntimeCatalog(),
        InMemoryRunCoordinator(),
        cancel_poll_seconds=0.01,
        observability_runtime=observability,
    )


async def create_thread(runtime: LangGraphRuntime, thread_id: str) -> None:
    await runtime.create_thread(thread_id=thread_id, metadata=None, if_exists=None)


async def wait_for_run(runtime: LangGraphRuntime, thread_id: str) -> str:
    while not (
        runs := await runtime.list_runs(
            thread_id,
            status=None,
            limit=10,
            offset=0,
        )
    ):
        await asyncio.sleep(0)
    return runs[0].run_id
