from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from arclith.adapters.outbound.opentelemetry.instrumentations.http import (
    sanitize_async_httpx_request_span,
    sanitize_fastapi_request_span,
    sanitize_httpx_request_span,
)


class RecordingSpan:
    def __init__(self, *, recording: bool = True) -> None:
        self.recording = recording
        self.attributes: dict[str, Any] = {}

    def is_recording(self) -> bool:
        return self.recording

    def set_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value


def test_fastapi_hook_removes_query_from_old_and_stable_url_attributes() -> None:
    span = RecordingSpan()
    scope = {
        "scheme": "https",
        "server": ("api.example.test", 443),
        "root_path": "/v1",
        "path": "/items",
        "query_string": b"token=secret&search=private",
    }

    sanitize_fastapi_request_span(span, scope)

    assert span.attributes == {
        "http.target": "/v1/items",
        "http.url": "https://api.example.test:443/v1/items",
        "url.full": "https://api.example.test:443/v1/items",
        "url.query": "",
    }
    assert "secret" not in repr(span.attributes)
    assert "private" not in repr(span.attributes)


@pytest.mark.asyncio
async def test_httpx_hooks_remove_every_query_parameter() -> None:
    request = SimpleNamespace(
        url=httpx.URL("https://api.example.test/items?token=secret&search=private")
    )
    sync_span = RecordingSpan()
    async_span = RecordingSpan()

    sanitize_httpx_request_span(sync_span, request)
    await sanitize_async_httpx_request_span(async_span, request)

    assert sync_span.attributes == {
        "http.url": "https://api.example.test/items",
        "url.full": "https://api.example.test/items",
    }
    assert async_span.attributes == sync_span.attributes


def test_http_hooks_are_noop_for_non_recording_spans() -> None:
    span = RecordingSpan(recording=False)

    sanitize_fastapi_request_span(span, {})
    sanitize_httpx_request_span(
        span,
        SimpleNamespace(url=httpx.URL("https://example.test/?secret=value")),
    )

    assert span.attributes == {}
