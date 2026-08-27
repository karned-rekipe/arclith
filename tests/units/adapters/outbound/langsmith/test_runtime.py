from __future__ import annotations

import builtins
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import langsmith
import pytest
from opentelemetry.sdk.trace import TracerProvider

from arclith.adapters.outbound.langsmith.runtime import (
    LangSmithRuntime,
    LangSmithTraceSpan,
)
from arclith.adapters.outbound.noop.observability import NoOpTraceSpan
from arclith.infrastructure.config import LangSmithSettings


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.flush_calls: list[float | None] = []
        self.close_calls: list[float | None] = []
        self.instances.append(self)

    def flush(self, timeout: float | None = None) -> None:
        self.flush_calls.append(timeout)

    def close(self, timeout: float | None = None) -> None:
        self.close_calls.append(timeout)


class FakeRunTree:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.end_calls: list[dict[str, Any]] = []

    def end(self, **kwargs: Any) -> None:
        self.end_calls.append(kwargs)

    def to_headers(self) -> dict[str, str]:
        return {
            "langsmith-trace": "trace-value",
            "baggage": (
                "langsmith-metadata=%7B%22safe%22%3A%22yes%22%2C"
                "%22secret%22%3A%22no%22%7D,langsmith-project=agent-tests"
            ),
        }


class FakeTraceContext:
    def __init__(self, run_tree: FakeRunTree, *, fail_enter: bool = False) -> None:
        self.run_tree = run_tree
        self.fail_enter = fail_enter
        self.exit_calls: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> FakeRunTree:
        if self.fail_enter:
            raise RuntimeError("export unavailable")
        return self.run_tree

    def __exit__(self, *exc_info: Any) -> None:
        self.exit_calls.append(exc_info)


class FakeProcessor:
    def __init__(self) -> None:
        self.flush_calls: list[int] = []
        self.shutdown_calls = 0

    def force_flush(self, timeout_millis: int) -> None:
        self.flush_calls.append(timeout_millis)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _runtime(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
    *,
    settings: dict[str, Any] | None = None,
    anonymizer: Any | None = None,
) -> tuple[LangSmithRuntime, list[dict[str, Any]], list[dict[str, Any]], FakeRunTree]:
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret-key")
    FakeClient.instances.clear()
    configure_calls: list[dict[str, Any]] = []
    trace_calls: list[dict[str, Any]] = []
    run_tree = FakeRunTree()

    monkeypatch.setattr(langsmith, "Client", FakeClient)
    monkeypatch.setattr(
        langsmith,
        "configure",
        lambda **kwargs: configure_calls.append(kwargs),
    )

    def fake_trace(name: str, **kwargs: Any) -> FakeTraceContext:
        trace_calls.append({"name": name, **kwargs})
        return FakeTraceContext(run_tree)

    monkeypatch.setattr(langsmith, "trace", fake_trace)

    @contextmanager
    def fake_tracing_context(**kwargs: Any) -> Iterator[None]:
        trace_calls.append({"context": kwargs})
        yield

    monkeypatch.setattr(langsmith, "tracing_context", fake_tracing_context)
    parsed = LangSmithSettings.model_validate(
        {
            "project": "agent-tests",
            "capture": {"inputs": True, "outputs": True, "metadata": True},
            **(settings or {}),
        }
    )
    runtime = LangSmithRuntime(
        parsed,
        logger,
        service_metadata={"service.name": "demo-api"},
        anonymizer=anonymizer,
    )
    return runtime, configure_calls, trace_calls, run_tree


def test_runtime_initializes_programmatically_without_mutating_environment(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, configure_calls, _trace_calls, _run_tree = _runtime(monkeypatch, logger)

    runtime.start()
    runtime.start()

    client = FakeClient.instances[0]
    assert len(FakeClient.instances) == 1
    assert client.kwargs["api_key"] == "secret-key"
    assert client.kwargs["api_url"] == "https://api.smith.langchain.com"
    assert client.kwargs["tracing_mode"] == "otel"
    assert client.kwargs["tracing_sampling_rate"] == 1.0
    assert configure_calls[0]["client"] is client
    assert configure_calls[0]["metadata"] == {"service.name": "demo-api"}
    assert runtime.client() is client
    assert runtime.diagnostics()["backend"] == "langsmith"


def test_runtime_forwards_project_owned_anonymizer(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    def redact(payload: dict[str, Any]) -> dict[str, Any]:
        return {"redacted": bool(payload)}

    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
        anonymizer=redact,
    )

    runtime.start()

    assert FakeClient.instances[0].kwargs["anonymizer"] is redact


def test_runtime_span_applies_capture_policy_and_finishes_run(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, trace_calls, run_tree = _runtime(monkeypatch, logger)

    with runtime.span(
        "resolve-intent",
        kind="tool",
        inputs={"prompt": "hello"},
        tags=("request",),
        metadata={"feature": "todo"},
    ) as span:
        assert isinstance(span, LangSmithTraceSpan)
        span.set_metadata({"result.kind": "create"})
        span.set_outputs({"result": "ok"})

    call = next(call for call in trace_calls if "name" in call)
    assert call["name"] == "resolve-intent"
    assert call["run_type"] == "tool"
    assert call["project_name"] is None
    assert call["inputs"] == {"prompt": "hello"}
    assert call["tags"] == ["arclith", "request"]
    assert call["metadata"]["service.name"] == "demo-api"
    assert run_tree.metadata == {"result.kind": "create"}
    assert run_tree.end_calls == [{"outputs": {"result": "ok"}}]


def test_runtime_span_preserves_business_errors(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
    )

    with pytest.raises(ValueError, match="business failure"):
        with runtime.span("failing-operation"):
            raise ValueError("business failure")


def test_runtime_span_is_noop_when_tracing_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
        settings={"tracing": {"enabled": False}},
    )

    with runtime.span("disabled") as span:
        assert isinstance(span, NoOpTraceSpan)

    assert trace_calls == []


def test_runtime_can_disable_automatic_langgraph_instrumentation(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, configure_calls, trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
        settings={"instrumentation": {"langgraph": False}},
    )

    runtime.start()
    with runtime.span("manual-span"):
        pass

    assert configure_calls[0]["enabled"] is False
    explicit_context = next(
        call["context"] for call in trace_calls if "context" in call
    )
    assert explicit_context["enabled"] is True


def test_runtime_runs_shared_provider_setup_before_automatic_attachment(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
    )
    events: list[str] = []
    runtime._opentelemetry_enabled = True
    runtime._before_start = lambda: events.append("configure")
    monkeypatch.setattr(
        runtime,
        "_attach_to_current_otel_provider",
        lambda: events.append("attach"),
    )

    runtime.start()

    assert events == ["configure", "attach"]


def test_runtime_context_can_override_tracing_and_preserves_body_errors(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, trace_calls, _run_tree = _runtime(monkeypatch, logger)

    with pytest.raises(ValueError, match="business failure"):
        with runtime.context(
            enabled=False,
            project="sensitive-project",
            parent={
                "langsmith-trace": "trace-value",
                "authorization": "Bearer secret",
            },
        ):
            context_call = trace_calls[0]["context"]
            assert context_call["enabled"] is False
            assert context_call["project_name"] == "sensitive-project"
            assert context_call["parent"] == {"langsmith-trace": "trace-value"}
            raise ValueError("business failure")


def test_runtime_propagates_only_allowlisted_baggage(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, run_tree = _runtime(
        monkeypatch,
        logger,
        settings={"propagation": {"baggage_allowlist": ["safe", "project"]}},
    )
    monkeypatch.setattr(
        "langsmith.run_helpers.get_current_run_tree",
        lambda: run_tree,
    )
    headers: dict[str, str] = {"authorization": "Bearer existing"}

    runtime.inject(headers)

    assert headers["langsmith-trace"] == "trace-value"
    assert "safe" in headers["baggage"]
    assert "secret" not in headers["baggage"]
    assert headers["authorization"] == "Bearer existing"


def test_runtime_is_fail_open_when_span_export_fails(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, run_tree = _runtime(monkeypatch, logger)
    monkeypatch.setattr(
        langsmith,
        "trace",
        lambda *args, **kwargs: FakeTraceContext(run_tree, fail_enter=True),
    )
    executed = False

    with runtime.span("unavailable") as span:
        executed = True
        assert isinstance(span, NoOpTraceSpan)

    assert executed is True
    assert logger.records[-1]["metadata"]["operation"] == "span.start"
    assert "secret-key" not in str(logger.records)


def test_runtime_can_raise_technical_failures_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, run_tree = _runtime(
        monkeypatch,
        logger,
        settings={"failure_mode": "raise"},
    )
    monkeypatch.setattr(
        langsmith,
        "trace",
        lambda *args, **kwargs: FakeTraceContext(run_tree, fail_enter=True),
    )

    with pytest.raises(RuntimeError, match="export unavailable"):
        with runtime.span("unavailable"):
            pass


def test_runtime_flush_and_close_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, configure_calls, _trace_calls, _run_tree = _runtime(monkeypatch, logger)
    runtime.start()
    processor = FakeProcessor()
    runtime._otel_processor = processor

    runtime.close(timeout=2.0)
    runtime.close(timeout=2.0)

    client = FakeClient.instances[0]
    assert processor.flush_calls == [2000]
    assert processor.shutdown_calls == 1
    assert client.flush_calls == [2.0]
    assert client.close_calls == [2.0]
    assert configure_calls[-1] == {
        "client": None,
        "enabled": None,
        "project_name": None,
        "tags": None,
        "metadata": None,
    }
    assert runtime.diagnostics()["closed"] is True


def test_runtime_builds_per_agent_pydantic_ai_instrumentation(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
        settings={
            "capture": {
                "inputs": False,
                "outputs": False,
                "metadata": True,
                "model_content": False,
                "binary_content": False,
                "model_request_parameters": False,
            }
        },
    )
    provider = TracerProvider()
    monkeypatch.setattr(runtime, "_ensure_pydantic_otel_provider", lambda: provider)

    capability = runtime.pydantic_ai_capability()

    assert capability is not None
    assert capability.settings.tracer.resource is provider.resource
    assert capability.settings.include_content is False
    assert capability.settings.include_binary_content is False
    assert capability.settings.include_model_request_parameters is False
    provider.shutdown()


def test_runtime_attaches_langsmith_processor_to_current_otel_provider(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
    )
    provider = TracerProvider()
    attached: list[Any] = []
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        runtime,
        "_attach_langsmith_processor",
        lambda selected: attached.append(selected),
    )

    runtime.attach_to_current_opentelemetry()

    assert attached == [provider]
    provider.shutdown()


def test_runtime_reuses_client_otel_provider_for_pydantic_ai(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    runtime, _configure_calls, _trace_calls, _run_tree = _runtime(
        monkeypatch,
        logger,
    )
    runtime.start()
    provider = TracerProvider()
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider",
        lambda: provider,
    )

    selected = runtime._ensure_pydantic_otel_provider()

    assert selected is provider
    assert runtime._otel_processor is None
    provider.shutdown()


def test_runtime_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
    logger: Any,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret-key")
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "langsmith":
            raise ModuleNotFoundError("missing", name="langsmith")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    runtime = LangSmithRuntime(LangSmithSettings(project="agent-tests"), logger)

    with pytest.raises(RuntimeError, match=r"arclith\[langsmith\]"):
        runtime.start()
