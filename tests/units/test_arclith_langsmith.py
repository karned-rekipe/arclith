from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

import pytest
import yaml
from fastapi.testclient import TestClient

from arclith import Arclith
from arclith.adapters.outbound.langsmith.runtime import LangSmithRuntime
from arclith.adapters.outbound.noop.observability import NoOpTraceAdapter
from arclith.domain.ports.outbound.observability import TracePort, TraceSpan
from arclith.infrastructure.observability_factory import (
    _configure_shared_opentelemetry,
)


class RecordingSpan(TraceSpan):
    def set_outputs(self, outputs: object | None) -> None:
        return None

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        return None


class RecordingTracer(TracePort):
    def __init__(self, capability: object | None = None) -> None:
        self.started = 0
        self.closed = 0
        self.capability = capability

    def start(self) -> None:
        self.started += 1

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
        yield RecordingSpan()

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
        self.closed += 1

    def pydantic_ai_capability(self) -> object | None:
        return self.capability


def _config_dir(tmp_path: Path, *, langsmith: dict[str, Any] | None = None) -> Path:
    config_dir = tmp_path / "config"
    (config_dir / "adapters" / "outbound").mkdir(parents=True)
    if langsmith is not None:
        (config_dir / "adapters" / "adapters.yaml").write_text(
            yaml.safe_dump({"observability": {"enabled": ["langsmith"]}}),
            encoding="utf-8",
        )
        (config_dir / "adapters" / "outbound" / "langsmith.yaml").write_text(
            yaml.safe_dump({"project": "agent-tests", **langsmith}),
            encoding="utf-8",
        )
    return config_dir


def test_arclith_returns_noop_tracer_by_default(tmp_path: Path) -> None:
    arclith = Arclith(_config_dir(tmp_path))

    assert isinstance(arclith.tracer(), NoOpTraceAdapter)
    assert arclith.observability_diagnostics() == {
        "backend": "noop",
        "tracing": False,
    }
    arclith.flush_observability()
    arclith.close_observability()


def test_arclith_builds_langsmith_runtime_only_when_selected(tmp_path: Path) -> None:
    arclith = Arclith(_config_dir(tmp_path, langsmith={"tracing": False}))

    assert isinstance(arclith.tracer(), LangSmithRuntime)
    assert arclith.observability_diagnostics()["started"] is False


def test_arclith_rejects_selected_langsmith_without_adapter_config(
    tmp_path: Path,
) -> None:
    arclith = Arclith(_config_dir(tmp_path))
    # Exercise the factory's defensive guard independently from AppConfig's
    # equivalent validation, for callers that assemble config programmatically.
    arclith.config.adapters.observability.enabled = ["langsmith"]

    with pytest.raises(RuntimeError, match="adapters.langsmith est absent"):
        arclith.tracer()


def test_shared_opentelemetry_setup_is_noop_without_complete_selection(
    tmp_path: Path,
) -> None:
    inactive = Arclith(_config_dir(tmp_path / "inactive")).config
    _configure_shared_opentelemetry(inactive)

    selected = Arclith(_config_dir(tmp_path / "selected")).config
    selected.adapters.observability.enabled = ["opentelemetry"]
    _configure_shared_opentelemetry(selected)


def test_arclith_forwards_provider_neutral_trace_anonymizer(tmp_path: Path) -> None:
    def redact(payload: dict[str, Any]) -> dict[str, Any]:
        return {"redacted": bool(payload)}

    arclith = Arclith(
        _config_dir(tmp_path, langsmith={}),
        trace_anonymizer=redact,
    )

    assert isinstance(arclith.tracer(), LangSmithRuntime)
    assert arclith.tracer()._anonymizer is redact


def test_arclith_langsmith_client_is_an_explicit_escape_hatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive = Arclith(_config_dir(tmp_path / "inactive"))
    with pytest.raises(RuntimeError, match="n'est pas active"):
        inactive.langsmith_client()

    active = Arclith(_config_dir(tmp_path / "active", langsmith={}))
    sentinel = object()
    monkeypatch.setattr(LangSmithRuntime, "client", lambda self: sentinel)

    assert active.langsmith_client() is sentinel


def test_fastapi_lifespan_starts_and_closes_observability(tmp_path: Path) -> None:
    arclith = Arclith(_config_dir(tmp_path))
    tracer = RecordingTracer()
    arclith.__dict__["_trace_adapter"] = tracer
    app = arclith.fastapi()

    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        assert tracer.started == 1

    assert tracer.closed == 1


def test_arclith_fastapi_adds_langsmith_instrumentation_when_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        "arclith.adapters.outbound.langsmith.fastapi.instrument_fastapi_app",
        lambda app, tracer: calls.append((app, tracer)),
    )
    arclith = Arclith(
        _config_dir(
            tmp_path,
            langsmith={"instrumentation": {"fastapi": True}},
        )
    )

    app = arclith.fastapi()

    assert calls == [(app, arclith.tracer())]


@pytest.mark.asyncio
async def test_arclith_fastmcp_instrumentation_is_idempotent(tmp_path: Path) -> None:
    arclith = Arclith(_config_dir(tmp_path, langsmith={}))
    arclith.__dict__["_trace_adapter"] = RecordingTracer()

    async def echo(value: str) -> str:
        return value

    component = SimpleNamespace(name="echo", fn=echo)
    mcp = SimpleNamespace(
        _local_provider=SimpleNamespace(_components={"echo": component})
    )

    arclith.instrument_mcp(mcp)
    first_wrapper = component.fn
    arclith.instrument_mcp(mcp)

    assert component.fn is first_wrapper
    assert await component.fn("ok") == "ok"


class GraphState(TypedDict, total=False):
    value: str


def test_langgraph_starts_configured_langsmith_runtime(tmp_path: Path) -> None:
    graph = pytest.importorskip("langgraph.graph")
    arclith = Arclith(_config_dir(tmp_path, langsmith={"tracing": False}))
    tracer = RecordingTracer()
    arclith.__dict__["_trace_adapter"] = tracer

    def register(builder: Any, _arclith: Arclith) -> None:
        builder.add_node("echo", lambda state: state)
        builder.add_edge(graph.START, "echo")
        builder.add_edge("echo", graph.END)

    compiled = arclith.langgraph(GraphState, register)

    assert tracer.started == 1
    assert compiled.invoke({"value": "ok"}) == {"value": "ok"}


def test_pydantic_ai_factory_injects_per_agent_capability(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    (config_dir / "adapters" / "outbound" / "lm.yaml").write_text(
        yaml.safe_dump(
            {
                "provider": "openai",
                "model_name": "local-model",
                "api_key": "local",
                "base_url": "http://localhost:1234/v1",
            }
        ),
        encoding="utf-8",
    )
    arclith = Arclith(config_dir)
    capability = object()
    arclith.__dict__["_trace_adapter"] = RecordingTracer(capability)

    adapter = arclith.pydantic_ai_llm()

    assert adapter._instrumentation is capability


def test_pydantic_ai_factory_requires_lm_config(tmp_path: Path) -> None:
    arclith = Arclith(_config_dir(tmp_path))

    with pytest.raises(RuntimeError, match="config.adapters.lm"):
        arclith.pydantic_ai_llm()
