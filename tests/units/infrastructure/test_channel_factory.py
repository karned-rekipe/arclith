from pathlib import Path

import pytest

from arclith import Arclith
from arclith.adapters.bidirectional.memory import MemoryChannel
from arclith.adapters.bidirectional.slack import SlackChannelSender
from arclith.adapters.bidirectional.webhook import WebhookCallbackSender
from arclith.domain.models.channel import ChannelDeliveryReceipt, ChannelOutgoingMessage
from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.infrastructure.channel_factory import (
    ChannelSenderRegistry,
    build_channel_sender,
)
from arclith.infrastructure.config import AppConfig


class StubSender(ChannelSender):
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        raise NotImplementedError


def _memory_config(*, enabled: bool = True) -> AppConfig:
    return AppConfig.model_validate(
        {"adapters": {"channel": {"memory": {"enabled": enabled}}}}
    )


def _webhook_config(
    *,
    enabled: bool = True,
    response_mode: str = "callback",
) -> AppConfig:
    webhook: dict[str, object] = {
        "enabled": enabled,
        "response_mode": response_mode,
    }
    if response_mode == "callback":
        webhook.update(
            callback_url="https://hooks.example.test/arclith",
            callback_allowed_host="hooks.example.test",
        )
    return AppConfig.model_validate({"adapters": {"channel": {"webhook": webhook}}})


def _slack_config(
    *,
    enabled: bool = True,
    bot_token: str | None = "xoxb-test",
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "adapters": {
                "channel": {
                    "slack": {
                        "enabled": enabled,
                        "bot_token": bot_token,
                    }
                }
            }
        }
    )


def test_build_channel_sender_returns_configured_memory_adapter(logger) -> None:
    sender = build_channel_sender(_memory_config(), logger, "memory")

    assert isinstance(sender, MemoryChannel)


def test_build_channel_sender_returns_configured_webhook_callback(logger) -> None:
    sender = build_channel_sender(_webhook_config(), logger, "webhook")

    assert isinstance(sender, WebhookCallbackSender)


def test_build_channel_sender_returns_configured_slack_adapter(logger) -> None:
    sender = build_channel_sender(_slack_config(), logger, "slack")

    assert isinstance(sender, SlackChannelSender)


@pytest.mark.parametrize("config", [AppConfig(), _memory_config(enabled=False)])
def test_build_channel_sender_requires_enabled_memory_config(config, logger) -> None:
    with pytest.raises(ValueError, match="memory.enabled=true"):
        build_channel_sender(config, logger, "memory")


@pytest.mark.parametrize(
    "config",
    [
        AppConfig(),
        _webhook_config(enabled=False),
        _webhook_config(response_mode="sync"),
    ],
)
def test_build_channel_sender_requires_webhook_callback_config(config, logger) -> None:
    with pytest.raises(ValueError, match="webhook"):
        build_channel_sender(config, logger, "webhook")


@pytest.mark.parametrize(
    "config",
    [AppConfig(), _slack_config(enabled=False), _slack_config(bot_token=None)],
)
def test_build_channel_sender_requires_enabled_slack_config(config, logger) -> None:
    with pytest.raises(ValueError, match="slack"):
        build_channel_sender(config, logger, "slack")


def test_channel_sender_registry_builds_custom_adapter(logger) -> None:
    expected = StubSender()
    registry = ChannelSenderRegistry().register(
        "custom", lambda _config, _logger: expected
    )

    assert (
        build_channel_sender(AppConfig(), logger, "custom", registry=registry)
        is expected
    )


def test_channel_sender_registry_rejects_invalid_adapter_names(logger) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ChannelSenderRegistry().register(" ", lambda _config, _logger: StubSender())
    with pytest.raises(ValueError, match="must not be empty"):
        build_channel_sender(AppConfig(), logger, " ")
    with pytest.raises(ValueError, match="not registered"):
        build_channel_sender(AppConfig(), logger, "unknown")


def test_arclith_builds_configured_channel_sender(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "adapters" / "bidirectional"
    config_dir.mkdir(parents=True)
    (config_dir / "memory.yaml").write_text("enabled: true\n", encoding="utf-8")

    sender = Arclith(tmp_path / "config").channel_sender("memory")

    assert isinstance(sender, MemoryChannel)
