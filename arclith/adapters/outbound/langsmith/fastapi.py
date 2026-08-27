from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from arclith.domain.ports.outbound.observability import TracePort


def instrument_fastapi_app(app: "FastAPI", tracer: "TracePort") -> None:
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
    except ImportError as exc:
        raise RuntimeError(
            'L\'instrumentation FastAPI LangSmith requiert "arclith[fastapi,langsmith]".'
        ) from exc

    class LangSmithTracingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            parent = {
                key.lower(): value
                for key, value in request.headers.items()
                if key.lower() in {"langsmith-trace", "traceparent", "baggage"}
            }
            with tracer.context(parent=parent):
                with tracer.span(
                    "http.server.request",
                    kind="chain",
                    metadata={
                        "http.request.method": request.method,
                        "url.scheme": request.url.scheme,
                    },
                ) as span:
                    response = await call_next(request)
                    route = request.scope.get("route")
                    route_path = getattr(route, "path", None)
                    metadata: dict[str, object] = {
                        "http.response.status_code": response.status_code,
                    }
                    if route_path:
                        metadata["http.route"] = route_path
                    span.set_metadata(metadata)
                    span.set_outputs({"status_code": response.status_code})
                    return response

    app.add_middleware(LangSmithTracingMiddleware)
