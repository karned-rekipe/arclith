from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from arclith.adapters.outbound.langsmith.runtime import LangSmithRuntime
from arclith.adapters.inbound.langgraph_runtime import (
    InMemoryRunCoordinator,
    InMemoryRuntimeCatalog,
    LangGraphRuntime,
    RunRequest,
)
from arclith.infrastructure.observability_factory import LangSmithObservabilityRuntime
from arclith.infrastructure.config import (
    LangSmithCaptureSettings,
    LangSmithSettings,
    LangSmithTracingSettings,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ARCLITH_LANGSMITH_INTEGRATION") != "1",
    reason="ARCLITH_LANGSMITH_INTEGRATION=1 non configure",
)


def test_langsmith_live_trace_is_queryable(logger) -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        pytest.fail("LANGSMITH_API_KEY est requis pour le test live LangSmith")

    project = os.getenv("LANGSMITH_PROJECT", "arclith-integration")
    run_name = f"arclith-integration-{uuid4().hex}"
    runtime = LangSmithRuntime(
        LangSmithSettings(
            project=project,
            tracing=LangSmithTracingSettings(mode="langsmith"),
            capture=LangSmithCaptureSettings(
                inputs=False,
                outputs=False,
                metadata=True,
            ),
        ),
        logger,
        service_metadata={"service.name": "arclith-integration"},
    )

    try:
        with runtime.span(run_name, metadata={"test.kind": "live"}) as span:
            span.set_outputs({"status": "ok"})
        runtime.flush(timeout=10.0)

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            runs = list(
                runtime.client().list_runs(
                    project_name=project,
                    filter=f'eq(name, "{run_name}")',
                    limit=1,
                )
            )
            if runs:
                assert runs[0].name == run_name
                break
            time.sleep(1.0)
        else:
            pytest.fail(f"run LangSmith introuvable apres flush: {run_name}")
    finally:
        runtime.close(timeout=10.0)


@pytest.mark.asyncio
async def test_langsmith_live_runtime_preserves_distributed_parent(logger) -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        pytest.fail("LANGSMITH_API_KEY est requis pour le test live LangSmith")

    project = os.getenv("LANGSMITH_PROJECT", "arclith-integration")
    parent_name = f"arclith-distributed-parent-{uuid4().hex}"
    producer = LangSmithRuntime(
        LangSmithSettings(
            project=project,
            tracing=LangSmithTracingSettings(mode="langsmith"),
            capture=LangSmithCaptureSettings(
                inputs=False,
                outputs=False,
                metadata=True,
            ),
        ),
        logger,
        service_metadata={"service.name": "arclith-producer-integration"},
    )
    consumer = LangSmithRuntime(
        LangSmithSettings(
            project=project,
            tracing=LangSmithTracingSettings(mode="langsmith"),
            capture=LangSmithCaptureSettings(
                inputs=False,
                outputs=False,
                metadata=True,
            ),
        ),
        logger,
        service_metadata={"service.name": "arclith-consumer-integration"},
    )

    class Graph:
        async def ainvoke(self, _value: Any, _config: Any) -> dict[str, str]:
            return {"status": "ok"}

        async def astream(
            self,
            value: Any,
            _config: Any,
            **_kwargs: Any,
        ) -> AsyncIterator[Any]:
            if False:
                yield value

    runtime = LangGraphRuntime(
        {"integration_agent": Graph()},
        InMemoryRuntimeCatalog(),
        InMemoryRunCoordinator(),
        observability_runtime=LangSmithObservabilityRuntime(consumer),
    )
    thread_id = str(uuid4())

    try:
        await runtime.create_thread(
            thread_id=thread_id,
            metadata=None,
            if_exists=None,
        )
        with producer.span(parent_name, metadata={"test.kind": "distributed"}):
            carrier: dict[str, str] = {}
            producer.inject(carrier)
            await runtime.wait(
                thread_id,
                RunRequest(
                    assistant_id="integration_agent",
                    trace_context=carrier,
                ),
            )
        producer.flush(timeout=10.0)
        consumer.flush(timeout=10.0)

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            parents = list(
                producer.client().list_runs(
                    project_name=project,
                    filter=f'eq(name, "{parent_name}")',
                    limit=1,
                )
            )
            if parents:
                children = list(
                    producer.client().list_runs(
                        project_name=project,
                        parent_run_id=parents[0].id,
                        limit=10,
                    )
                )
                boundary = next(
                    (run for run in children if run.name == "langgraph.runtime.run"),
                    None,
                )
                if boundary is not None:
                    assert boundary.trace_id == parents[0].trace_id
                    assert boundary.parent_run_id == parents[0].id
                    break
            await asyncio.sleep(1.0)
        else:
            pytest.fail("hierarchie LangSmith distribuee introuvable apres flush")
    finally:
        consumer.close(timeout=10.0)
        producer.close(timeout=10.0)
