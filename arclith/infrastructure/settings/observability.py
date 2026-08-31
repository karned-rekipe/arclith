from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from arclith.infrastructure.settings._base import SettingsModel

ObservabilityAdapter = Literal["langsmith", "opentelemetry"]


class ObservabilitySettings(SettingsModel):
    enabled: list[ObservabilityAdapter] = Field(default_factory=list)

    @field_validator("enabled")
    @classmethod
    def must_not_contain_duplicates(
        cls, v: list[ObservabilityAdapter]
    ) -> list[ObservabilityAdapter]:
        if len(v) != len(set(v)):
            raise ValueError("observability.enabled ne doit pas contenir de doublons")
        return v

    def is_enabled(self, adapter: ObservabilityAdapter) -> bool:
        return adapter in self.enabled
