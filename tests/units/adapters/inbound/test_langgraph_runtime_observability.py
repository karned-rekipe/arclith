from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from arclith.adapters.inbound.langgraph_runtime import (
    InMemoryRunCoordinator,
    InMemoryRuntimeCatalog,
    LangGraphRuntime,
    RunRequest,
    create_langgraph_runtime_app,
)
from arclith.adapters.inbound.langgraph_runtime.runtime import RunCancelledError
from tests.units.adapters.inbound.langgraph_runtime_observability_fakes import (
    RecordingGraph,
    RecordingObservability,
    build_runtime,
    create_thread,
    wait_for_run,
)

THREAD_ID = "01993fb0-7a3d-71a0-9c20-d7abbd755180"
SECOND_THREAD_ID = "01993fb0-7a3d-71a0-9c20-d7abbd755181"


def test_http_wait_and_stream_only_attach_sanitized_trace_context() -> None:
    observability = RecordingObservability()
    graph = RecordingGraph(observability.current)
    runtime = build_runtime(observability, graph)
    client = TestClient(create_langgraph_runtime_app(runtime))
    assert client.post("/threads", json={"thread_id": THREAD_ID}).status_code == 200
    headers = {
        "LangSmith-Trace": "trace-value",
        "TraceParent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        "TraceState": "vendor=value",
        "Baggage": "safe=yes,secret=no",
        "Authorization": "Bearer sensitive",
        "Cookie": "session=sensitive",
        "X-API-Key": "sensitive",
    }
    payload = {"assistant_id": "test_agent", "input": {"status": "requested"}}

    waited = client.post(
        f"/threads/{THREAD_ID}/runs/wait",
        json=payload,
        headers=headers,
    )
    streamed = client.post(
        f"/threads/{THREAD_ID}/runs/stream",
        json=payload,
        headers=headers,
    )

    expected = {
        "langsmith-trace": "trace-value",
        "traceparent": headers["TraceParent"],
        "tracestate": "vendor=value",
        "baggage": "safe=yes",
    }
    assert waited.status_code == 200
    assert streamed.status_code == 200
    assert graph.parents == [expected, expected]
    spans = [value for event, value in observability.events if event == "span.enter"]
    assert len(spans) == 2
    assert all(span["name"] == "langgraph.runtime.run" for span in spans)
    assert all(span["kind"] == "server" for span in spans)
    assert all(span["inputs"] is None for span in spans)
    assert all(
        set(span["metadata"])
        == {
            "langgraph.thread_id",
            "langgraph.run_id",
            "langgraph.assistant_id",
        }
        for span in spans
    )
    assert [
        value for event, value in observability.events if event == "span.metadata"
    ] == [
        {"langgraph.run.status": "success"},
        {"langgraph.run.status": "success"},
    ]
    stored = json.dumps(client.get(f"/threads/{THREAD_ID}/runs").json())
    assert "trace-value" not in stored
    assert "Bearer sensitive" not in stored
    assert "session=sensitive" not in stored
    assert "secret=no" not in stored


def test_disabled_observability_extracts_nothing() -> None:
    runtime = LangGraphRuntime(
        {"test_agent": object()},
        InMemoryRuntimeCatalog(),
        InMemoryRunCoordinator(),
    )

    assert (
        runtime.extract_trace_context(
            {
                "traceparent": "00-trace-parent-01",
                "baggage": "safe=yes",
                "authorization": "Bearer sensitive",
            }
        )
        == {}
    )


@pytest.mark.asyncio
async def test_wait_and_stream_release_trace_context_after_errors() -> None:
    wait_observability = RecordingObservability()
    wait_runtime = build_runtime(
        wait_observability,
        RecordingGraph(wait_observability.current, fail=True),
    )
    await create_thread(wait_runtime, THREAD_ID)
    request = RunRequest(
        assistant_id="test_agent",
        trace_context={"traceparent": "wait-parent", "authorization": "sensitive"},
    )

    with pytest.raises(ValueError, match="graph failed"):
        await wait_runtime.wait(THREAD_ID, request)

    assert (await wait_runtime.get_thread(THREAD_ID)).status == "error"
    assert ("span.exception", "ValueError") in wait_observability.events
    assert any(event == "context.exit" for event, _value in wait_observability.events)

    stream_observability = RecordingObservability()
    stream_runtime = build_runtime(
        stream_observability,
        RecordingGraph(stream_observability.current, fail=True),
    )
    await create_thread(stream_runtime, SECOND_THREAD_ID)
    chunks = [
        chunk
        async for chunk in stream_runtime.stream(
            SECOND_THREAD_ID,
            RunRequest(
                assistant_id="test_agent",
                trace_context={"traceparent": "stream-parent"},
            ),
        )
    ]

    assert b"GraphExecutionError" in b"".join(chunks)
    assert (await stream_runtime.get_thread(SECOND_THREAD_ID)).status == "error"
    assert ("span.exception", "ValueError") in stream_observability.events
    assert any(event == "context.exit" for event, _value in stream_observability.events)


@pytest.mark.asyncio
async def test_wait_and_stream_release_trace_context_after_cancellation() -> None:
    wait_observability = RecordingObservability()
    wait_runtime = build_runtime(
        wait_observability,
        RecordingGraph(wait_observability.current, delay=30),
    )
    await create_thread(wait_runtime, THREAD_ID)
    wait_task = asyncio.create_task(
        wait_runtime.wait(
            THREAD_ID,
            RunRequest(
                assistant_id="test_agent",
                trace_context={"traceparent": "wait-parent"},
            ),
        )
    )
    wait_run_id = await wait_for_run(wait_runtime, THREAD_ID)
    await wait_runtime.cancel_run(THREAD_ID, wait_run_id)

    with pytest.raises(RunCancelledError):
        await asyncio.wait_for(wait_task, timeout=1)

    assert ("span.exception", "RunCancelledError") in wait_observability.events
    assert any(event == "context.exit" for event, _value in wait_observability.events)

    stream_observability = RecordingObservability()
    stream_runtime = build_runtime(
        stream_observability,
        RecordingGraph(stream_observability.current, delay=30),
    )
    await create_thread(stream_runtime, SECOND_THREAD_ID)

    async def consume_stream() -> list[bytes]:
        return [
            chunk
            async for chunk in stream_runtime.stream(
                SECOND_THREAD_ID,
                RunRequest(
                    assistant_id="test_agent",
                    trace_context={"traceparent": "stream-parent"},
                ),
            )
        ]

    stream_task = asyncio.create_task(consume_stream())
    stream_run_id = await wait_for_run(stream_runtime, SECOND_THREAD_ID)
    await stream_runtime.cancel_run(SECOND_THREAD_ID, stream_run_id)
    chunks = await asyncio.wait_for(stream_task, timeout=1)

    assert b"RunCancelledError" in b"".join(chunks)
    assert ("span.exception", "RunCancelledError") in stream_observability.events
    assert any(event == "context.exit" for event, _value in stream_observability.events)
