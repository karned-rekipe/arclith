"""Shared validation for generated HTTP path templates."""

from __future__ import annotations

import re


_PATH_PARAMETER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")


def http_path_parameters(path: str) -> tuple[str, ...]:
    """Return validated parameter names from a fixed FastAPI path template."""
    parameters = tuple(_PATH_PARAMETER_RE.findall(path))
    remainder = _PATH_PARAMETER_RE.sub("", path)
    if "{" in remainder or "}" in remainder:
        raise ValueError("HTTP path parameters must use the {field_name} syntax")
    if len(parameters) != len(set(parameters)):
        raise ValueError("HTTP path parameters must be unique")
    return parameters
