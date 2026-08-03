from __future__ import annotations

import functools
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


class MetricsRegistry:
    """Thread-safe counter/gauge store shared by all collectors."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, float]] = {}

    def increment(self, bucket: str, name: str, delta: float = 1.0) -> None:
        with self._lock:
            b = self._data.setdefault(bucket, {})
            b[name] = b.get(name, 0.0) + delta

    def gauge(self, bucket: str, name: str, value: float) -> None:
        with self._lock:
            self._data.setdefault(bucket, {})[name] = value

    def get(self, bucket: str, name: str, default: float = 0.0) -> float:
        with self._lock:
            return self._data.get(bucket, {}).get(name, default)

    def raw_snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {t: dict(m) for t, m in self._data.items()}


class ApiMetricsCollector:
    """Starlette ASGI middleware — instruments every HTTP request.

    Tracks: request_count, latency_avg_ms, error_count, error_rate.
    Attach via ``app.add_middleware(ApiMetricsCollector, registry=registry)``.
    """

    transport = "api"

    def __init__(self, app: Any, registry: MetricsRegistry) -> None:
        self._app = app
        self._registry = registry

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start = time.monotonic()
        status_code = [500]

        async def _send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, _send_wrapper)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._registry.increment("api", "request_count")
            self._registry.increment("api", "_latency_sum_ms", elapsed_ms)
            self._registry.increment("api", "_latency_count")
            if status_code[0] >= 400:
                self._registry.increment("api", "error_count")

    def collect(self) -> dict[str, float | int]:
        reg = self._registry
        request_count = int(reg.get("api", "request_count"))
        error_count = int(reg.get("api", "error_count"))
        latency_sum = reg.get("api", "_latency_sum_ms")
        latency_count = reg.get("api", "_latency_count")
        return {
            "request_count": request_count,
            "latency_avg_ms": round(latency_sum / latency_count, 2) if latency_count else 0.0,
            "error_count": error_count,
            "error_rate": round(error_count / request_count, 4) if request_count else 0.0,
        }


class McpMetricsCollector:
    """Instruments FastMCP tool calls.

    Usage (Option B — explicit, called after register_tools)::

        arclith.instrument_mcp(mcp)
    """

    transport = "mcp"

    def __init__(self, registry: MetricsRegistry, logger: "Any | None" = None) -> None:
        self._registry = registry
        self._logger = logger

    def wrap(self, tool_name: str, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """Wrap an async MCP tool function to record call/latency/failure metrics."""
        registry = self._registry
        logger = self._logger

        @functools.wraps(fn)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            registry.increment("mcp", "tool_calls_total")
            registry.increment(f"mcp._tool.{tool_name}", "calls")
            start = time.monotonic()
            ok = True
            try:
                result = await fn(*args, **kwargs)
                return result
            except Exception:
                ok = False
                registry.increment("mcp", "failures")
                registry.increment(f"mcp._tool.{tool_name}", "failures")
                raise
            finally:
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                registry.increment("mcp", "_latency_sum_ms", elapsed_ms)
                registry.increment("mcp", "_latency_count")
                registry.increment(f"mcp._tool.{tool_name}", "_latency_sum_ms", elapsed_ms)
                registry.increment(f"mcp._tool.{tool_name}", "_latency_count")
                if logger:
                    logger.info(f"⏱ mcp.{tool_name}", duration_ms=elapsed_ms, ok=ok)

        return _wrapper

    def record_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Call from your LLM handler to track token usage."""
        self._registry.increment("mcp", "token_usage_input", float(input_tokens))
        self._registry.increment("mcp", "token_usage_output", float(output_tokens))

    def collect(self) -> dict[str, Any]:
        reg = self._registry
        total_calls = int(reg.get("mcp", "tool_calls_total"))
        failures = int(reg.get("mcp", "failures"))
        latency_sum = reg.get("mcp", "_latency_sum_ms")
        latency_count = reg.get("mcp", "_latency_count")

        by_tool: dict[str, dict[str, Any]] = {}
        for bucket, values in reg.raw_snapshot().items():
            if not bucket.startswith("mcp._tool."):
                continue
            name = bucket[len("mcp._tool."):]
            t_calls = int(values.get("calls", 0))
            t_fail = int(values.get("failures", 0))
            t_sum = values.get("_latency_sum_ms", 0.0)
            t_cnt = values.get("_latency_count", 0.0)
            by_tool[name] = {
                "calls": t_calls,
                "failures": t_fail,
                "latency_avg_ms": round(t_sum / t_cnt, 2) if t_cnt else 0.0,
            }

        return {
            "tool_calls_total": total_calls,
            "failures": failures,
            "latency_avg_ms": round(latency_sum / latency_count, 2) if latency_count else 0.0,
            "token_usage": {
                "input": int(reg.get("mcp", "token_usage_input")),
                "output": int(reg.get("mcp", "token_usage_output")),
            },
            "by_tool": by_tool,
        }


@runtime_checkable
class EventBusCollectorProtocol(Protocol):
    """Protocol à implémenter pour les collecteurs Event Bus (Kafka, Redis Streams…).

    Métriques attendues:
        messages_consumed_total, processing_duration_ms,
        consumer_lag, failures, retries
    """

    transport: str

    def collect(self) -> dict[str, float | int | dict[str, Any]]: ...

