from __future__ import annotations

from typing import Any
from urllib.parse import urlunsplit


def sanitize_fastapi_request_span(span: Any, scope: dict[str, Any]) -> None:
    """Replace request URL attributes with a query-free representation."""

    if span is None or not span.is_recording():
        return
    path = f"{scope.get('root_path', '')}{scope.get('path', '')}" or "/"
    server = scope.get("server")
    authority = _server_authority(server)
    safe_url = urlunsplit((scope.get("scheme", "http"), authority, path, "", ""))
    span.set_attribute("http.target", path)
    span.set_attribute("http.url", safe_url)
    span.set_attribute("url.full", safe_url)
    span.set_attribute("url.query", "")


def sanitize_httpx_request_span(span: Any, request: Any) -> None:
    """Remove every query parameter from outbound HTTP span URLs."""

    if span is None or not span.is_recording():
        return
    safe_url = str(request.url.copy_with(query=None, fragment=None))
    span.set_attribute("http.url", safe_url)
    span.set_attribute("url.full", safe_url)


async def sanitize_async_httpx_request_span(span: Any, request: Any) -> None:
    sanitize_httpx_request_span(span, request)


def _server_authority(server: Any) -> str:
    if not server:
        return ""
    host, port = server
    if port is None:
        return str(host)
    return f"{host}:{port}"
