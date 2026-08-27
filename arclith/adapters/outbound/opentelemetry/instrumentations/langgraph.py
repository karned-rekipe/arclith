from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from arclith.domain.ports.outbound.observability import MetricPort, TracePort

_OBSERVATION_ACTIVE: ContextVar[bool] = ContextVar(
    "arclith_langgraph_observation_active", default=False
)


def instrument_langgraph(
    graph: Any,
    tracer: TracePort,
    metrics: MetricPort,
    *,
    name: str,
) -> Any:
    """Observe workflow boundaries without exporting graph state or results."""

    if getattr(graph, "__arclith_otel_instrumented__", False):
        return graph
    _wrap_invoke(graph, tracer, metrics, name)
    _wrap_ainvoke(graph, tracer, metrics, name)
    _wrap_stream(graph, tracer, metrics, name)
    _wrap_astream(graph, tracer, metrics, name)
    setattr(graph, "__arclith_otel_instrumented__", True)
    return graph


def _wrap_invoke(graph: Any, tracer: TracePort, metrics: MetricPort, name: str) -> None:
    original = graph.invoke

    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _observe(tracer, metrics, graph_name=name, operation="invoke"):
            return original(*args, **kwargs)

    graph.invoke = wrapped


def _wrap_ainvoke(
    graph: Any, tracer: TracePort, metrics: MetricPort, name: str
) -> None:
    original = graph.ainvoke

    @wraps(original)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _observe(tracer, metrics, graph_name=name, operation="invoke"):
            return await original(*args, **kwargs)

    graph.ainvoke = wrapped


def _wrap_stream(graph: Any, tracer: TracePort, metrics: MetricPort, name: str) -> None:
    original = graph.stream

    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Iterator[Any]:
        with _observe(tracer, metrics, graph_name=name, operation="stream"):
            yield from original(*args, **kwargs)

    graph.stream = wrapped


def _wrap_astream(
    graph: Any, tracer: TracePort, metrics: MetricPort, name: str
) -> None:
    original = graph.astream

    @wraps(original)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _observe(tracer, metrics, graph_name=name, operation="stream"):
            async for event in original(*args, **kwargs):
                yield event

    graph.astream = wrapped


@contextmanager
def _observe(
    tracer: TracePort,
    metrics: MetricPort,
    *,
    graph_name: str,
    operation: str,
) -> Iterator[None]:
    if _OBSERVATION_ACTIVE.get():
        yield
        return
    started_at = time.perf_counter()
    token = _OBSERVATION_ACTIVE.set(True)
    try:
        try:
            with tracer.span(
                "arclith.langgraph.workflow",
                metadata={
                    "arclith.langgraph.convention.version": "1",
                    "arclith.langgraph.name": graph_name,
                    "arclith.langgraph.operation.name": operation,
                },
            ) as span:
                yield
                span.set_outputs({"status": "success"})
        except BaseException as exc:
            _record_metrics(metrics, started_at, operation, type(exc).__name__)
            raise
        _record_metrics(metrics, started_at, operation, "none")
    finally:
        _OBSERVATION_ACTIVE.reset(token)


def _record_metrics(
    metrics: MetricPort,
    started_at: float,
    operation: str,
    error_type: str,
) -> None:
    attributes = {
        "arclith.langgraph.operation.name": operation,
        "error.type": error_type,
    }
    metrics.add_counter(
        "arclith.langgraph.operations",
        attributes=attributes,
        description="LangGraph workflow operations processed by Arclith",
    )
    metrics.record_histogram(
        "arclith.langgraph.duration",
        (time.perf_counter() - started_at) * 1000,
        attributes=attributes,
        description="LangGraph workflow operation duration",
    )
