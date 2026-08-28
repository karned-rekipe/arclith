from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, MessagesState, StateGraph

from arclith.adapters.inbound.langgraph_runtime import (
    InMemoryRunCoordinator,
    InMemoryRuntimeCatalog,
    LangGraphRuntime,
    RunBusyError,
    RunRequest,
    create_langgraph_runtime_app,
    load_graphs,
)
from arclith.adapters.inbound.langgraph_runtime.runtime import (
    RunCancelledError,
    _graph_config,
    _run_input,
    _stream_item,
    _stream_modes,
)

THREAD_ID = "01993fb0-7a3d-71a0-9c20-d7abbd755180"


def _graph(*, delay: float = 0, fail: bool = False) -> Any:
    builder = StateGraph(MessagesState)

    async def respond(state: MessagesState) -> dict[str, Any]:
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise ValueError("graph failed")
        writer = get_stream_writer()
        writer({"kind": "progress", "message": "working"})
        content = _last_content(state.get("messages", []))
        return {"messages": [AIMessage(content=f"Echo: {content}")]}

    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=InMemorySaver())


def _last_content(messages: list[BaseMessage]) -> str:
    return str(messages[-1].content) if messages else ""


def _runtime(graph: Any | None = None) -> LangGraphRuntime:
    return LangGraphRuntime(
        {"test_agent": graph or _graph()},
        InMemoryRuntimeCatalog(),
        InMemoryRunCoordinator(),
        cancel_poll_seconds=0.01,
    )


def test_runtime_validates_configuration_and_exposes_assistants() -> None:
    with pytest.raises(ValueError, match="au moins un graphe"):
        LangGraphRuntime({}, InMemoryRuntimeCatalog(), InMemoryRunCoordinator())
    with pytest.raises(ValueError, match="run_timeout_seconds"):
        LangGraphRuntime(
            {"test": _graph()},
            InMemoryRuntimeCatalog(),
            InMemoryRunCoordinator(),
            run_timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="cancel_poll_seconds"):
        LangGraphRuntime(
            {"test": _graph()},
            InMemoryRuntimeCatalog(),
            InMemoryRunCoordinator(),
            cancel_poll_seconds=0,
        )

    runtime = _runtime()
    assert runtime.assistants()[0]["metadata"] == {"runtime": "arclith-open-source"}


def test_http_runtime_exposes_thread_run_history_and_sse_contract() -> None:
    runtime = _runtime()
    client = TestClient(create_langgraph_runtime_app(runtime))

    assert client.get("/info").status_code == 200
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.post("/assistants/search", json={}).json()[0]["assistant_id"] == (
        "test_agent"
    )
    assert client.get("/assistants/test_agent").status_code == 200
    assert client.get("/assistants/missing").status_code == 404

    created = client.post(
        "/threads",
        json={"thread_id": THREAD_ID, "metadata": {"tenant": "one"}},
    )
    assert created.status_code == 200
    assert created.json()["thread_id"] == THREAD_ID
    assert created.json()["status"] == "idle"
    assert client.get(f"/threads/{THREAD_ID}").status_code == 200
    assert (
        client.post("/threads/search", json={"metadata": {"tenant": "one"}}).json()[0][
            "thread_id"
        ]
        == THREAD_ID
    )
    assert client.get(f"/threads/{THREAD_ID}/state").json()["values"] == {}

    waited = client.post(
        f"/threads/{THREAD_ID}/runs/wait",
        json={
            "assistant_id": "test_agent",
            "input": {"messages": [{"role": "user", "content": "bonjour"}]},
        },
    )
    assert waited.status_code == 200
    assert waited.json()["messages"][-1]["content"] == "Echo: bonjour"

    history = client.post(f"/threads/{THREAD_ID}/history", json={"limit": 100})
    assert history.status_code == 200
    assert history.json()[0]["checkpoint"]["thread_id"] == THREAD_ID
    assert history.json()[0]["values"]["messages"][-1]["content"] == "Echo: bonjour"
    assert (
        client.get(f"/threads/{THREAD_ID}/state").json()["values"]["messages"][-1][
            "content"
        ]
        == "Echo: bonjour"
    )

    streamed = client.post(
        f"/threads/{THREAD_ID}/runs/stream",
        json={
            "assistant_id": "test_agent",
            "input": {"messages": [{"role": "user", "content": "suite"}]},
            "stream_mode": ["values", "custom"],
        },
        headers={"Accept": "text/event-stream"},
    )
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: metadata" in streamed.text
    assert "event: custom" in streamed.text
    assert "event: values" in streamed.text
    assert "Echo: suite" in streamed.text

    runs = client.get(f"/threads/{THREAD_ID}/runs").json()
    assert [run["status"] for run in runs] == ["success", "success"]
    run_id = runs[0]["run_id"]
    assert client.get(f"/threads/{THREAD_ID}/runs/{run_id}").status_code == 200
    assert client.post(f"/threads/{THREAD_ID}/runs/{run_id}/cancel").status_code == 204

    deleted = client.delete(f"/threads/{THREAD_ID}")
    assert deleted.status_code == 204
    assert client.get(f"/threads/{THREAD_ID}").status_code == 404


def test_http_runtime_maps_validation_conflicts_and_execution_errors() -> None:
    runtime = _runtime(_graph(fail=True))
    client = TestClient(
        create_langgraph_runtime_app(runtime),
        raise_server_exceptions=False,
    )
    client.post("/threads", json={"thread_id": THREAD_ID})

    duplicate = client.post(
        "/threads",
        json={"thread_id": THREAD_ID, "if_exists": "raise"},
    )
    unknown = client.post(
        "/threads/01993fb0-7a3d-71a0-9c20-d7abbd755181/runs/wait",
        json={"assistant_id": "test_agent"},
    )
    missing_assistant = client.post(
        f"/threads/{THREAD_ID}/runs/wait",
        json={"assistant_id": "missing"},
    )
    failed = client.post(
        f"/threads/{THREAD_ID}/runs/wait",
        json={"assistant_id": "test_agent", "input": {"messages": []}},
    )
    unsupported_strategy = client.post(
        f"/threads/{THREAD_ID}/runs/wait",
        json={"assistant_id": "test_agent", "multitask_strategy": "enqueue"},
    )

    assert duplicate.status_code == 409
    assert unknown.status_code == 404
    assert missing_assistant.status_code == 404
    assert failed.status_code == 500
    assert unsupported_strategy.status_code == 422
    assert client.get(f"/threads/{THREAD_ID}").json()["status"] == "error"


def test_http_runtime_sanitizes_stream_errors_and_reports_storage_readiness() -> None:
    runtime = _runtime(_graph(fail=True))
    client = TestClient(create_langgraph_runtime_app(runtime))
    client.post("/threads", json={"thread_id": THREAD_ID})

    failed = client.post(
        f"/threads/{THREAD_ID}/runs/stream",
        json={
            "assistant_id": "test_agent",
            "input": {"messages": [{"role": "user", "content": "secret"}]},
        },
    )
    assert failed.status_code == 200
    assert "GraphExecutionError" in failed.text
    assert "graph failed" not in failed.text
    assert client.get(f"/threads/{THREAD_ID}").json()["status"] == "error"

    class UnhealthyCoordinator(InMemoryRunCoordinator):
        async def healthcheck(self) -> bool:
            return False

    unavailable = LangGraphRuntime(
        {"test_agent": _graph()},
        InMemoryRuntimeCatalog(),
        UnhealthyCoordinator(),
    )
    unavailable_client = TestClient(create_langgraph_runtime_app(unavailable))
    assert unavailable_client.get("/ready").status_code == 503


@pytest.mark.asyncio
async def test_runtime_cancels_an_active_run_and_persists_status() -> None:
    runtime = _runtime(_graph(delay=30))
    await runtime.setup()
    await runtime.create_thread(
        thread_id=THREAD_ID,
        metadata=None,
        if_exists=None,
    )
    task = asyncio.create_task(
        runtime.wait(
            THREAD_ID,
            RunRequest(
                assistant_id="test_agent",
                input={"messages": [{"role": "user", "content": "slow"}]},
            ),
        )
    )
    while not (
        runs := await runtime.list_runs(
            THREAD_ID,
            status=None,
            limit=10,
            offset=0,
        )
    ):
        await asyncio.sleep(0)

    await runtime.cancel_run(THREAD_ID, runs[0].run_id)
    with pytest.raises(RunCancelledError):
        await task

    stored = await runtime.get_run(THREAD_ID, runs[0].run_id)
    assert stored.status == "interrupted"
    assert (await runtime.get_thread(THREAD_ID)).status == "interrupted"


@pytest.mark.asyncio
async def test_runtime_cancels_an_active_stream_with_sanitized_sse() -> None:
    runtime = _runtime(_graph(delay=30))
    await runtime.create_thread(
        thread_id=THREAD_ID,
        metadata=None,
        if_exists=None,
    )

    async def consume() -> list[bytes]:
        return [
            chunk
            async for chunk in runtime.stream(
                THREAD_ID,
                RunRequest(
                    assistant_id="test_agent",
                    input={"messages": [{"role": "user", "content": "slow"}]},
                ),
            )
        ]

    task = asyncio.create_task(consume())
    while not (
        runs := await runtime.list_runs(
            THREAD_ID,
            status=None,
            limit=10,
            offset=0,
        )
    ):
        await asyncio.sleep(0)

    await runtime.cancel_run(THREAD_ID, runs[0].run_id)
    chunks = await task
    assert b'"error":"RunCancelledError"' in b"".join(chunks)
    assert (await runtime.get_run(THREAD_ID, runs[0].run_id)).status == ("interrupted")


@pytest.mark.asyncio
async def test_in_memory_coordinator_rejects_concurrent_thread_runs() -> None:
    coordinator = InMemoryRunCoordinator()

    async with coordinator.thread_lock(THREAD_ID, timeout_seconds=10):
        with pytest.raises(RunBusyError):
            async with coordinator.thread_lock(THREAD_ID, timeout_seconds=10):
                pass

    assert await coordinator.healthcheck() is True
    await coordinator.close()


@pytest.mark.asyncio
async def test_state_and_history_use_the_graph_from_the_latest_run() -> None:
    first_graph = _graph()
    second_graph = _graph()
    runtime = LangGraphRuntime(
        {"first": first_graph, "second": second_graph},
        InMemoryRuntimeCatalog(),
        InMemoryRunCoordinator(),
        cancel_poll_seconds=0.01,
    )
    await runtime.create_thread(
        thread_id=THREAD_ID,
        metadata=None,
        if_exists=None,
    )
    await runtime.wait(
        THREAD_ID,
        RunRequest(
            assistant_id="second",
            input={"messages": [{"role": "user", "content": "second graph"}]},
        ),
    )

    state = await runtime.state(THREAD_ID)
    history = await runtime.history(THREAD_ID, limit=10)
    assert state["values"]["messages"][-1]["content"] == "Echo: second graph"
    assert history[0]["values"]["messages"][-1]["content"] == ("Echo: second graph")
    assert (await first_graph.aget_state(_graph_config(THREAD_ID, None))).values == {}


@pytest.mark.asyncio
async def test_busy_run_does_not_create_a_second_record_or_change_status() -> None:
    runtime = _runtime(_graph(delay=30))
    await runtime.create_thread(
        thread_id=THREAD_ID,
        metadata=None,
        if_exists=None,
    )
    task = asyncio.create_task(
        runtime.wait(
            THREAD_ID,
            RunRequest(
                assistant_id="test_agent",
                input={"messages": [{"role": "user", "content": "slow"}]},
            ),
        )
    )
    while not (
        runs := await runtime.list_runs(
            THREAD_ID,
            status=None,
            limit=10,
            offset=0,
        )
    ):
        await asyncio.sleep(0)

    with pytest.raises(RunBusyError):
        await runtime.wait(
            THREAD_ID,
            RunRequest(assistant_id="test_agent", input={"messages": []}),
        )
    busy_stream = b"".join(
        [
            chunk
            async for chunk in runtime.stream(
                THREAD_ID,
                RunRequest(assistant_id="test_agent", input={"messages": []}),
            )
        ]
    )
    assert b'"error":"RunBusyError"' in busy_stream
    assert (
        len(
            await runtime.list_runs(
                THREAD_ID,
                status=None,
                limit=10,
                offset=0,
            )
        )
        == 1
    )
    assert (await runtime.get_thread(THREAD_ID)).status == "busy"

    await runtime.cancel_run(THREAD_ID, runs[0].run_id)
    with pytest.raises(RunCancelledError):
        await task


def test_runtime_request_helpers_preserve_resume_and_stream_contract() -> None:
    request = RunRequest(
        assistant_id="test",
        input={"ignored": True},
        command={"resume": "approved"},
        config={"configurable": {"tenant": "one"}},
        checkpoint={"checkpoint_id": "checkpoint", "checkpoint_ns": "namespace"},
    )
    command = _run_input(request)
    assert command.resume == "approved"
    assert _graph_config(THREAD_ID, request)["configurable"] == {
        "tenant": "one",
        "thread_id": THREAD_ID,
        "checkpoint_id": "checkpoint",
        "checkpoint_ns": "namespace",
    }
    assert _graph_config(THREAD_ID, None) == {"configurable": {"thread_id": THREAD_ID}}
    assert _stream_modes(None) == ["values"]
    assert _stream_modes(["messages-tuple", "custom", "custom"]) == [
        "messages",
        "custom",
    ]
    assert _stream_item(("custom", {"value": 1}), ["values", "custom"]) == (
        "custom",
        {"value": 1},
    )
    assert _stream_item({"value": 1}, ["values"]) == (
        "values",
        {"value": 1},
    )


def test_load_graphs_supports_src_entrypoints_and_rejects_invalid_contract(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    package = tmp_path / "src" / "demo_runtime"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "graph.py").write_text(
        """
class Graph:
    async def ainvoke(self, value, config):
        return value
    async def astream(self, value, config, **kwargs):
        if False:
            yield value
graph = Graph()
bad = object()
""",
        encoding="utf-8",
    )
    config = tmp_path / "langgraph.json"
    config.write_text(
        json.dumps({"graphs": {"demo": "./src/demo_runtime/graph.py:graph"}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("ARCLITH_LANGGRAPH_PERSISTENCE_MODE", "embedded")
    assert list(load_graphs(config)) == ["demo"]
    assert os.environ["ARCLITH_LANGGRAPH_PERSISTENCE_MODE"] == "agent_server"

    config.write_text(
        json.dumps({"graphs": {"demo": "./src/demo_runtime/graph.py:bad"}}),
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="ainvoke"):
        load_graphs(config)

    config.write_text(json.dumps({"graphs": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="au moins un graphe"):
        load_graphs(config)


def test_load_graphs_supports_module_entrypoints_and_rejects_bad_configs(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import sys

    module = tmp_path / "runtime_module.py"
    module.write_text(
        """
class Graph:
    async def ainvoke(self, value, config):
        return value
    async def astream(self, value, config, **kwargs):
        if False:
            yield value
graph = Graph()
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config = tmp_path / "module.json"
    config.write_text(
        json.dumps({"graphs": {"module": "runtime_module:graph"}}),
        encoding="utf-8",
    )
    assert list(load_graphs(config)) == ["module"]
    sys.modules.pop("runtime_module", None)

    invalid_payloads = [
        {},
        {"graphs": {"": "runtime_module:graph"}},
        {"graphs": {"demo": 42}},
        {"graphs": {"demo": "missing_separator"}},
        {"graphs": {"demo": "runtime_module:missing"}},
        {"graphs": {"demo": "./missing.py:graph"}},
    ]
    for index, payload in enumerate(invalid_payloads):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises((ValueError, AttributeError, FileNotFoundError)):
            load_graphs(path)
