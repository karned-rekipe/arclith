from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from arclith.domain.ports.outbound.observability import MetricPort, TracePort

if TYPE_CHECKING:
    import fastmcp as _fastmcp

    from arclith.arclith import Arclith


class McpInstrumentation:
    """Instrument FastMCP components independently from application bootstrap."""

    def __init__(self, owner: "Arclith") -> None:
        self._owner = owner

    def instrument_mcp(self, mcp: "_fastmcp.FastMCP") -> None:
        """Wrap registered FastMCP tools with metrics and optional tracing.

        Call AFTER all tools are registered::

            IngredientMCP(service, logger, mcp)
            arclith.instrument_mcp(mcp)
        """
        collector = (
            self._owner._mcp_collector if self._owner.config.probe.enabled else None
        )
        tracer = self._selected_mcp_tracer()
        metrics = self._selected_mcp_metrics()
        if collector is None and tracer is None and metrics is None:
            return
        components = self._mcp_components(mcp)
        if components is None:
            return
        count = sum(
            self._instrument_mcp_component(component, collector, tracer, metrics)
            for component in components.values()
        )
        self._owner.logger.info("🔬 MCP tools instrumented", count=count)

    def _selected_mcp_tracer(self) -> TracePort | None:
        langsmith = self._owner.config.adapters.langsmith
        otel = self._owner.config.adapters.opentelemetry
        selected = (
            self._owner.config.adapters.observability.is_enabled("langsmith")
            and langsmith is not None
            and langsmith.instrumentation.fastmcp
        ) or (
            self._owner.config.adapters.observability.is_enabled("opentelemetry")
            and otel is not None
            and otel.instrumentation.fastmcp
            and otel.signals.traces.enabled
        )
        return self._owner.tracer() if selected else None

    def _selected_mcp_metrics(self) -> MetricPort | None:
        settings = self._owner.config.adapters.opentelemetry
        if not self._owner.config.adapters.observability.is_enabled("opentelemetry"):
            return None
        if (
            settings is None
            or not settings.instrumentation.fastmcp
            or not settings.signals.metrics.enabled
        ):
            return None
        return self._owner._observability_runtime.metrics

    def _mcp_components(self, mcp: "_fastmcp.FastMCP") -> dict[str, Any] | None:
        try:
            # fastmcp 3.x: FunctionTool objects are kept on the local provider.
            return mcp._local_provider._components  # type: ignore[attr-defined,no-any-return]
        except AttributeError:
            self._owner.logger.warning(
                "⚠️ instrument_mcp: cannot access FastMCP components (API changed?)"
            )
            return None

    def _instrument_mcp_component(
        self,
        component: Any,
        collector: Any | None,
        tracer: TracePort | None,
        metrics: MetricPort | None,
    ) -> int:
        fn = getattr(component, "fn", None)
        if fn is None or not callable(fn):
            return 0
        if getattr(fn, "__arclith_instrumented__", False):
            return 0
        wrapped = collector.wrap(component.name, fn) if collector is not None else fn
        if (tracer is not None or metrics is not None) and not getattr(
            wrapped, "__arclith_traced__", False
        ):
            wrapped = self._wrap_mcp_trace(
                component.name,
                wrapped,
                tracer,
                metrics,
            )
        setattr(wrapped, "__arclith_instrumented__", True)
        component.fn = wrapped
        return 1

    @staticmethod
    def _wrap_mcp_trace(
        name: str,
        fn: Callable,
        tracer: TracePort | None,
        metrics: MetricPort | None = None,
    ) -> Callable:
        from arclith.adapters.outbound.noop.observability import NoOpTraceAdapter

        selected_tracer = tracer or NoOpTraceAdapter()
        metadata = {
            "arclith.mcp.convention.version": "1",
            "arclith.mcp.method.name": name,
            "arclith.mcp.operation.name": "tools/call",
        }

        def _record_metrics(started_at: float, outcome: str) -> None:
            if metrics is None:
                return
            attributes = {
                "rpc.system": "mcp",
                "rpc.method": "tools/call",
                "error.type": outcome,
            }
            metrics.add_counter(
                "arclith.mcp.requests",
                attributes=attributes,
                description="MCP calls processed by Arclith",
            )
            metrics.record_histogram(
                "arclith.mcp.duration",
                (time.perf_counter() - started_at) * 1000,
                attributes=attributes,
                description="MCP call duration",
            )

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
                started_at = time.perf_counter()
                try:
                    with selected_tracer.span(
                        "arclith.mcp.tool", kind="server", metadata=metadata
                    ) as span:
                        result = await fn(*args, **kwargs)
                        span.set_outputs({"status": "success"})
                        _record_metrics(started_at, "none")
                        return result
                except BaseException as exc:
                    _record_metrics(started_at, type(exc).__name__)
                    raise

            setattr(_async_wrapped, "__arclith_traced__", True)
            return _async_wrapped

        @wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                with selected_tracer.span(
                    "arclith.mcp.tool", kind="server", metadata=metadata
                ) as span:
                    result = fn(*args, **kwargs)
                    span.set_outputs({"status": "success"})
                    _record_metrics(started_at, "none")
                    return result
            except BaseException as exc:
                _record_metrics(started_at, type(exc).__name__)
                raise

        setattr(_wrapped, "__arclith_traced__", True)
        return _wrapped
