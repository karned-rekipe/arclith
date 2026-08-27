from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any, TypedDict

import pytest

from arclith.adapters.outbound.opentelemetry.instrumentations.langgraph import (
    instrument_langgraph,
)
from arclith.adapters.outbound.noop.observability import NoOpMetricAdapter
from arclith.domain.ports.outbound.observability import TracePort, TraceSpan


class RecordingSpan(TraceSpan):
    def __init__(self) -> None:
        self.outputs: object | None = None

    def set_outputs(self, outputs: object | None) -> None:
        self.outputs = outputs

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        return None


class RecordingTracer(TracePort):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        span = RecordingSpan()
        call = {"name": name, "metadata": dict(metadata or {}), "span": span}
        self.calls.append(call)
        yield span

    @contextmanager
    def context(self, **kwargs: Any) -> Iterator[None]:
        yield

    def inject(self, headers: MutableMapping[str, str]) -> None:
        return None

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None


class FakeGraph:
    def invoke(self, state: dict[str, str]) -> dict[str, str]:
        return {"result": state["secret"]}

    async def ainvoke(self, state: dict[str, str]) -> dict[str, str]:
        return self.invoke(state)

    def stream(self, state: dict[str, str]) -> Iterator[dict[str, str]]:
        yield self.invoke(state)

    async def astream(self, state: dict[str, str]) -> Any:
        yield self.invoke(state)


@pytest.mark.asyncio
async def test_langgraph_boundaries_cover_sync_async_and_stream_without_state() -> None:
    tracer = RecordingTracer()
    graph = FakeGraph()

    assert (
        instrument_langgraph(graph, tracer, NoOpMetricAdapter(), name="agent") is graph
    )
    assert (
        instrument_langgraph(graph, tracer, NoOpMetricAdapter(), name="agent") is graph
    )

    assert graph.invoke({"secret": "private"}) == {"result": "private"}
    assert await graph.ainvoke({"secret": "private"}) == {"result": "private"}
    assert list(graph.stream({"secret": "private"})) == [{"result": "private"}]
    assert [item async for item in graph.astream({"secret": "private"})] == [
        {"result": "private"}
    ]

    assert len(tracer.calls) == 4
    assert {
        call["metadata"]["arclith.langgraph.operation.name"] for call in tracer.calls
    } == {
        "invoke",
        "stream",
    }
    assert "private" not in repr(tracer.calls)
    assert all(call["span"].outputs == {"status": "success"} for call in tracer.calls)


def test_langgraph_boundary_records_error_without_state() -> None:
    tracer = RecordingTracer()
    graph = FakeGraph()
    instrument_langgraph(graph, tracer, NoOpMetricAdapter(), name="agent")

    with pytest.raises(KeyError):
        graph.invoke({})

    assert len(tracer.calls) == 1
    assert "secret" not in repr(tracer.calls)


def test_compiled_langgraph_is_instrumented_in_place_without_nested_duplicates() -> (
    None
):
    graph_api = pytest.importorskip("langgraph.graph")

    class State(TypedDict):
        value: int

    builder = graph_api.StateGraph(State)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.add_edge(graph_api.START, "increment")
    builder.add_edge("increment", graph_api.END)
    graph = builder.compile()
    tracer = RecordingTracer()

    instrument_langgraph(graph, tracer, NoOpMetricAdapter(), name="counter")

    assert graph.invoke({"value": 1}) == {"value": 2}
    assert len(tracer.calls) == 1
    assert tracer.calls[0]["metadata"]["arclith.langgraph.name"] == "counter"
