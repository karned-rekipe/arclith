from __future__ import annotations

import threading
from typing import Any

import pytest

from arclith.adapters.inbound.probes.metrics import (
    ApiMetricsCollector,
    EventBusCollectorProtocol,
    McpMetricsCollector,
    MetricsRegistry,
)


# ── MetricsRegistry ───────────────────────────────────────────────────────────

class TestMetricsRegistry:
    def test_increment_creates_and_accumulates(self):
        reg = MetricsRegistry()
        reg.increment("api", "hits")
        reg.increment("api", "hits")
        reg.increment("api", "hits", 3.0)
        assert reg.get("api", "hits") == 5.0

    def test_gauge_sets_value(self):
        reg = MetricsRegistry()
        reg.gauge("api", "latency", 42.5)
        assert reg.get("api", "latency") == 42.5

    def test_gauge_overwrites(self):
        reg = MetricsRegistry()
        reg.gauge("mcp", "score", 1.0)
        reg.gauge("mcp", "score", 99.0)
        assert reg.get("mcp", "score") == 99.0

    def test_get_missing_returns_default(self):
        reg = MetricsRegistry()
        assert reg.get("nope", "nope") == 0.0
        assert reg.get("nope", "nope", 7.0) == 7.0

    def test_raw_snapshot_is_copy(self):
        reg = MetricsRegistry()
        reg.increment("api", "x", 1.0)
        snap = reg.raw_snapshot()
        snap["api"]["x"] = 999.0
        assert reg.get("api", "x") == 1.0

    def test_multiple_buckets(self):
        reg = MetricsRegistry()
        reg.increment("api", "a", 1.0)
        reg.increment("mcp", "b", 2.0)
        snap = reg.raw_snapshot()
        assert snap == {"api": {"a": 1.0}, "mcp": {"b": 2.0}}

    def test_thread_safety(self):
        reg = MetricsRegistry()
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                for _ in range(100):
                    reg.increment("api", "counter")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert reg.get("api", "counter") == 1000.0


# ── ApiMetricsCollector ───────────────────────────────────────────────────────

class TestApiMetricsCollector:
    def _make_simple_app(self, status: int = 200) -> Any:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def endpoint(_: Request) -> JSONResponse:
            return JSONResponse({}, status_code=status)

        return Starlette(routes=[Route("/test", endpoint)])

    def test_collect_initial_zeros(self):
        reg = MetricsRegistry()
        col = ApiMetricsCollector(app=None, registry=reg)  # type: ignore[arg-type]
        result = col.collect()
        assert result == {
            "request_count": 0,
            "latency_avg_ms": 0.0,
            "error_count": 0,
            "error_rate": 0.0,
        }

    async def test_middleware_counts_requests(self):
        from starlette.testclient import TestClient

        reg = MetricsRegistry()
        inner = self._make_simple_app(200)
        middleware = ApiMetricsCollector(app=inner, registry=reg)

        with TestClient(middleware) as client:
            client.get("/test")
            client.get("/test")

        col = ApiMetricsCollector(app=None, registry=reg)  # type: ignore[arg-type]
        result = col.collect()
        assert result["request_count"] == 2
        assert result["error_count"] == 0
        assert result["error_rate"] == 0.0
        assert result["latency_avg_ms"] > 0

    async def test_middleware_tracks_errors(self):
        from starlette.testclient import TestClient

        reg = MetricsRegistry()
        inner = self._make_simple_app(500)
        middleware = ApiMetricsCollector(app=inner, registry=reg)

        with TestClient(middleware, raise_server_exceptions=False) as client:
            client.get("/test")
            client.get("/test")

        col = ApiMetricsCollector(app=None, registry=reg)  # type: ignore[arg-type]
        result = col.collect()
        assert result["request_count"] == 2
        assert result["error_count"] == 2
        assert result["error_rate"] == 1.0

    async def test_middleware_passes_non_http_scopes(self):
        reg = MetricsRegistry()
        received: list[dict] = []

        async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
            received.append(scope)

        middleware = ApiMetricsCollector(app=dummy_app, registry=reg)
        await middleware({"type": "lifespan"}, None, None)

        assert len(received) == 1
        assert reg.get("api", "request_count") == 0.0

    def test_error_rate_no_requests(self):
        reg = MetricsRegistry()
        col = ApiMetricsCollector(app=None, registry=reg)  # type: ignore[arg-type]
        assert col.collect()["error_rate"] == 0.0

    def test_latency_avg_no_requests(self):
        reg = MetricsRegistry()
        col = ApiMetricsCollector(app=None, registry=reg)  # type: ignore[arg-type]
        assert col.collect()["latency_avg_ms"] == 0.0

    def test_transport_name(self):
        assert ApiMetricsCollector.transport == "api"


# ── McpMetricsCollector ───────────────────────────────────────────────────────

class TestMcpMetricsCollector:
    async def test_wrap_records_success(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)

        async def my_tool(x: int) -> int:
            return x + 1

        wrapped = col.wrap("my_tool", my_tool)
        result = await wrapped(x=5)
        assert result == 6

        metrics = col.collect()
        assert metrics["tool_calls_total"] == 1
        assert metrics["failures"] == 0
        assert metrics["by_tool"]["my_tool"]["calls"] == 1
        assert metrics["by_tool"]["my_tool"]["failures"] == 0
        assert metrics["by_tool"]["my_tool"]["latency_avg_ms"] >= 0.0

    async def test_wrap_records_failure(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)

        async def bad_tool() -> None:
            raise ValueError("boom")

        wrapped = col.wrap("bad_tool", bad_tool)
        with pytest.raises(ValueError, match="boom"):
            await wrapped()

        metrics = col.collect()
        assert metrics["tool_calls_total"] == 1
        assert metrics["failures"] == 1
        assert metrics["by_tool"]["bad_tool"]["failures"] == 1

    async def test_wrap_preserves_function_name(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)

        async def original_name() -> None:
            pass

        wrapped = col.wrap("original_name", original_name)
        assert wrapped.__name__ == "original_name"

    async def test_multiple_tools(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)

        async def tool_a() -> str:
            return "a"

        async def tool_b() -> str:
            return "b"

        wrapped_a = col.wrap("tool_a", tool_a)
        wrapped_b = col.wrap("tool_b", tool_b)
        await wrapped_a()
        await wrapped_a()
        await wrapped_b()

        metrics = col.collect()
        assert metrics["tool_calls_total"] == 3
        assert metrics["by_tool"]["tool_a"]["calls"] == 2
        assert metrics["by_tool"]["tool_b"]["calls"] == 1

    def test_record_tokens(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)
        col.record_tokens(input_tokens=100, output_tokens=50)

        metrics = col.collect()
        assert metrics["token_usage"]["input"] == 100
        assert metrics["token_usage"]["output"] == 50

    def test_collect_empty(self):
        reg = MetricsRegistry()
        col = McpMetricsCollector(reg)
        metrics = col.collect()
        assert metrics["tool_calls_total"] == 0
        assert metrics["failures"] == 0
        assert metrics["by_tool"] == {}
        assert metrics["token_usage"] == {"input": 0, "output": 0}

    def test_transport_name(self):
        assert McpMetricsCollector.transport == "mcp"


# ── EventBusCollectorProtocol ─────────────────────────────────────────────────

class TestEventBusCollectorProtocol:
    def test_is_runtime_checkable(self):
        class MyCollector:
            transport = "event_bus"

            def collect(self) -> dict:
                return {}

        assert isinstance(MyCollector(), EventBusCollectorProtocol)

    def test_missing_collect_fails(self):
        class BadCollector:
            transport = "event_bus"

        assert not isinstance(BadCollector(), EventBusCollectorProtocol)
