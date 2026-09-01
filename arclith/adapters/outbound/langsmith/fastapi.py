from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arclith.adapters.outbound.langsmith.propagation import (
    normalized_parent_headers,
)
from arclith.infrastructure.config import LangSmithPropagationSettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from arclith.domain.ports.outbound.observability import TracePort


def instrument_fastapi_app(
    app: "FastAPI",
    tracer: "TracePort",
    *,
    propagation: LangSmithPropagationSettings | None = None,
) -> None:
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
    except ImportError as exc:
        raise RuntimeError(
            'L\'instrumentation FastAPI LangSmith requiert "arclith[fastapi,langsmith]".'
        ) from exc

    settings = propagation or LangSmithPropagationSettings()

    class LangSmithTracingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            parent = (
                normalized_parent_headers(
                    request.headers,
                    allowlist=set(settings.baggage_allowlist),
                    langsmith_headers=settings.langsmith_headers,
                    traceparent=settings.traceparent,
                )
                if settings.enabled
                else {}
            )
            with (
                tracer.context(parent=parent),
                tracer.span(
                    "http.server.request",
                    kind="chain",
                    metadata={
                        "http.request.method": request.method,
                        "url.scheme": request.url.scheme,
                    },
                ) as span,
            ):
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
