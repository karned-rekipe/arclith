from __future__ import annotations

from arclith.infrastructure.settings._base import SettingsModel


class MemoryChannelSettings(SettingsModel):
    """Dependency-free channel adapter settings for tests and local POCs."""

    enabled: bool = True


class ChannelSettings(SettingsModel):
    """Configuration sections for provider-neutral channel adapters."""

    memory: MemoryChannelSettings | None = None

    def configured_adapters(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("memory",)
            if (settings := getattr(self, name)) is not None and settings.enabled
        )
