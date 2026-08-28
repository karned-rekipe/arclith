from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from arclith.adapters.inbound.langgraph_runtime.server import (
    create_durable_langgraph_runtime_app,
)

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("ARCLITH_TEST_POSTGRESQL_URL") and os.getenv("ARCLITH_TEST_REDIS_URL")
    ),
    reason="ARCLITH_TEST_POSTGRESQL_URL et ARCLITH_TEST_REDIS_URL non configures",
)

CONFIG_PATH = Path(__file__).parent / "fixtures" / "langgraph-runtime.json"


def _app():
    return create_durable_langgraph_runtime_app(
        CONFIG_PATH,
        database_uri=os.environ["ARCLITH_TEST_POSTGRESQL_URL"],
        redis_uri=os.environ["ARCLITH_TEST_REDIS_URL"],
        redis_prefix="arclith:integration-runtime",
    )


def test_durable_runtime_resumes_after_complete_server_restart() -> None:
    thread_id = str(uuid4())
    with TestClient(_app()) as first_server:
        created = first_server.post(
            "/threads",
            json={"thread_id": thread_id, "metadata": {"test": "integration"}},
        )
        assert created.status_code == 200
        first_run = first_server.post(
            f"/threads/{thread_id}/runs/wait",
            json={
                "assistant_id": "integration_agent",
                "input": {"messages": [{"role": "user", "content": "premier"}]},
            },
        )
        assert first_run.status_code == 200
        assert first_run.json()["messages"][-1]["content"] == "Echo: premier"

    with TestClient(_app()) as second_server:
        try:
            restored = second_server.get(f"/threads/{thread_id}/state")
            assert restored.status_code == 200
            assert restored.json()["values"]["messages"][-1]["content"] == (
                "Echo: premier"
            )

            second_run = second_server.post(
                f"/threads/{thread_id}/runs/wait",
                json={
                    "assistant_id": "integration_agent",
                    "input": {"messages": [{"role": "user", "content": "suite"}]},
                },
            )
            assert second_run.status_code == 200
            assert second_run.json()["messages"][-1]["content"] == "Echo: suite"

            history = second_server.post(
                f"/threads/{thread_id}/history",
                json={"limit": 100},
            )
            assert history.status_code == 200
            assert len(history.json()) >= 4
            runs = second_server.get(f"/threads/{thread_id}/runs")
            assert [run["status"] for run in runs.json()] == [
                "success",
                "success",
            ]
        finally:
            assert second_server.delete(f"/threads/{thread_id}").status_code == 204
