from __future__ import annotations

from typing import Any


def render(template: str, variables: dict[str, Any]) -> str:
    """Render one trusted catalog template with its validated parameters."""
    return template.format(**variables)
