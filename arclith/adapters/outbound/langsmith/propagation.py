from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping

_LANGSMITH_TRACE = "langsmith-trace"
_BAGGAGE = "baggage"
_TRACEPARENT = "traceparent"
_TRACESTATE = "tracestate"


def normalized_parent_headers(
    headers: Mapping[str, str] | None,
    *,
    allowlist: set[str],
    langsmith_headers: bool,
    traceparent: bool,
) -> dict[str, str]:
    if not headers:
        return {}
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    result: dict[str, str] = {}
    if langsmith_headers and normalized.get(_LANGSMITH_TRACE):
        result[_LANGSMITH_TRACE] = normalized[_LANGSMITH_TRACE]
    if traceparent and normalized.get(_TRACEPARENT):
        result[_TRACEPARENT] = normalized[_TRACEPARENT]
        if normalized.get(_TRACESTATE):
            result[_TRACESTATE] = normalized[_TRACESTATE]
    baggage = filter_baggage(normalized.get(_BAGGAGE, ""), allowlist=allowlist)
    if baggage:
        result[_BAGGAGE] = baggage
    return result


def filter_baggage(value: str, *, allowlist: set[str]) -> str:
    if not value or not allowlist:
        return ""
    filtered: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        safe_item = _filtered_baggage_item(item, allowlist=allowlist)
        if safe_item:
            filtered.append(safe_item)
    return ",".join(filtered)


def _filtered_baggage_item(item: str, *, allowlist: set[str]) -> str | None:
    key, separator, encoded = item.partition("=")
    if separator != "=" or not key:
        return None
    if key == "langsmith-metadata":
        metadata = _filtered_metadata(encoded, allowlist=allowlist)
        if not metadata:
            return None
        serialized = json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        return f"{key}={urllib.parse.quote(serialized)}"
    aliases = {"langsmith-tags": "tags", "langsmith-project": "project"}
    allowed_key = aliases.get(key, key)
    return item if allowed_key in allowlist else None


def merge_baggage(*values: str) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_item in value.split(","):
            item = raw_item.strip()
            key = item.partition("=")[0]
            if item and key not in seen:
                seen.add(key)
                items.append(item)
    return ",".join(items)


def _filtered_metadata(encoded: str, *, allowlist: set[str]) -> dict[str, object]:
    try:
        loaded = json.loads(urllib.parse.unquote(encoded))
    except (ValueError, TypeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): value for key, value in loaded.items() if str(key) in allowlist}
