from __future__ import annotations

from typing import Literal

from arclith.infrastructure.settings._base import SettingsModel


class LMSettings(SettingsModel):
    provider: Literal["anthropic", "openai"] = "anthropic"
    model_name: str = "claude-sonnet-4-5"
    api_key: str = ""
    base_url: str | None = None  # requis si provider="openai" (LLM local/custom)
