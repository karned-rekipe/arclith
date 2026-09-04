from __future__ import annotations

from collections.abc import Callable

from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.domain.ports.outbound.logger import Logger
from arclith.infrastructure.config import AppConfig

ChannelSenderFactory = Callable[[AppConfig, Logger], ChannelSender]


class ChannelSenderRegistry:
    """Registry mapping channel adapter names to outbound sender factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ChannelSenderFactory] = {}

    def register(
        self,
        name: str,
        factory: ChannelSenderFactory,
    ) -> "ChannelSenderRegistry":
        normalized = name.strip()
        if not normalized:
            raise ValueError("Channel adapter name must not be empty")
        self._factories[normalized] = factory
        return self

    def build(
        self,
        adapter: str,
        config: AppConfig,
        logger: Logger,
    ) -> ChannelSender:
        if adapter not in self._factories:
            raise ValueError(
                f"Channel adapter '{adapter}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[adapter](config, logger)


def build_channel_sender(
    config: AppConfig,
    logger: Logger,
    adapter: str,
    *,
    registry: ChannelSenderRegistry | None = None,
) -> ChannelSender:
    """Build one explicitly selected channel sender."""

    normalized = adapter.strip()
    if not normalized:
        raise ValueError("Channel adapter name must not be empty")
    active_registry = registry or default_channel_sender_registry()
    return active_registry.build(normalized, config, logger)


def default_channel_sender_registry() -> ChannelSenderRegistry:
    return (
        ChannelSenderRegistry()
        .register("memory", _build_memory_channel)
        .register("webhook", _build_webhook_callback_sender)
        .register("slack", _build_slack_channel_sender)
    )


def _build_memory_channel(config: AppConfig, _logger: Logger) -> ChannelSender:
    settings = config.adapters.channel.memory
    if settings is None or not settings.enabled:
        raise ValueError(
            "adapters.channel.memory.enabled=true is required to build "
            "the memory channel adapter"
        )
    from arclith.adapters.bidirectional.memory import MemoryChannel

    return MemoryChannel()


def _build_webhook_callback_sender(
    config: AppConfig,
    _logger: Logger,
) -> ChannelSender:
    settings = config.adapters.channel.webhook
    if settings is None or not settings.enabled:
        raise ValueError(
            "adapters.channel.webhook.enabled=true is required to build "
            "the webhook channel adapter"
        )
    if settings.response_mode != "callback":
        raise ValueError(
            "adapters.channel.webhook.response_mode=callback is required to build "
            "a standalone webhook channel sender"
        )
    from arclith.adapters.bidirectional.webhook import WebhookCallbackSender

    return WebhookCallbackSender(settings)


def _build_slack_channel_sender(
    config: AppConfig,
    _logger: Logger,
) -> ChannelSender:
    settings = config.adapters.channel.slack
    if settings is None or not settings.enabled:
        raise ValueError(
            "adapters.channel.slack.enabled=true is required to build "
            "the Slack channel adapter"
        )
    from arclith.adapters.bidirectional.slack import SlackChannelSender

    return SlackChannelSender(settings)
