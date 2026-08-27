from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest

from arclith.adapters.outbound.langsmith.runtime import LangSmithRuntime
from arclith.infrastructure.config import LangSmithSettings

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
            tracing={"mode": "langsmith"},
            capture={"inputs": False, "outputs": False, "metadata": True},
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
