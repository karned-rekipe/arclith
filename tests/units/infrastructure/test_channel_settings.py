from __future__ import annotations

import pytest
from pydantic import ValidationError

from arclith.infrastructure.settings.channel import (
    ChannelSettings,
    SlackChannelSettings,
    WebhookChannelSettings,
)


def test_webhook_settings_have_secure_bounded_defaults() -> None:
    settings = WebhookChannelSettings()

    assert settings.path == "/channels/webhook"
    assert settings.secret is None
    assert settings.signature_tolerance_seconds == 300
    assert settings.event_ttl_seconds == 86_400
    assert settings.max_payload_bytes == 1_048_576
    assert settings.response_mode == "sync"


def test_webhook_settings_redact_configured_secret() -> None:
    secret = "a-secure-webhook-secret-with-32-bytes"
    settings = WebhookChannelSettings(secret=secret)

    assert secret not in repr(settings)
    assert settings.model_dump(mode="json")["secret"] == "**********"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "channels/webhook"),
        ("path", "/channels/{provider}"),
        ("path", "/channels/webhook/"),
        ("signature_header", "bad header"),
        ("secret", "too-short"),
        ("secret", " " * 32),
        ("signature_tolerance_seconds", 0),
        ("max_payload_bytes", 0),
    ],
)
def test_webhook_settings_reject_invalid_security_boundaries(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        WebhookChannelSettings.model_validate({field: value})


def test_webhook_settings_require_distinct_headers_and_unique_metadata() -> None:
    with pytest.raises(ValidationError, match="headers must differ"):
        WebhookChannelSettings(
            signature_header="X-Event",
            idempotency_header="x-event",
        )
    with pytest.raises(ValidationError, match="unique names"):
        WebhookChannelSettings(metadata_allowlist=("trace_id", "trace_id"))


def test_webhook_callback_settings_require_an_exact_safe_https_host() -> None:
    settings = WebhookChannelSettings(
        response_mode="callback",
        callback_url="https://hooks.example.test/arclith",
        callback_allowed_host="HOOKS.EXAMPLE.TEST.",
    )

    assert settings.callback_allowed_host == "hooks.example.test"

    with pytest.raises(ValidationError, match="must match"):
        WebhookChannelSettings(
            response_mode="callback",
            callback_url="https://hooks.example.test/arclith",
            callback_allowed_host="other.example.test",
        )


@pytest.mark.parametrize(
    ("callback_url", "callback_host"),
    [
        ("http://hooks.example.test/callback", "hooks.example.test"),
        ("https://user:pass@hooks.example.test/callback", "hooks.example.test"),
        ("https://hooks.example.test/callback?token=secret", "hooks.example.test"),
        ("https://127.0.0.1/callback", "127.0.0.1"),
        ("https://localhost/callback", "localhost"),
        ("https://not a host/callback", "not a host"),
        ("https://hooks.example.test:invalid/callback", "hooks.example.test"),
    ],
)
def test_webhook_callback_settings_reject_unsafe_targets(
    callback_url: str,
    callback_host: str,
) -> None:
    with pytest.raises(ValidationError):
        WebhookChannelSettings(
            response_mode="callback",
            callback_url=callback_url,
            callback_allowed_host=callback_host,
        )


def test_channel_settings_list_only_enabled_adapters() -> None:
    settings = ChannelSettings.model_validate(
        {
            "memory": {"enabled": False},
            "webhook": {"enabled": True},
            "slack": {"enabled": True},
        }
    )

    assert settings.configured_adapters() == ("webhook", "slack")


def test_callback_fields_are_forbidden_outside_callback_mode() -> None:
    with pytest.raises(ValidationError, match="require response_mode=callback"):
        WebhookChannelSettings(callback_allowed_host="hooks.example.test")


def test_slack_settings_have_secure_bounded_defaults() -> None:
    settings = SlackChannelSettings()

    assert settings.path == "/channels/slack/events"
    assert settings.signing_secret is None
    assert settings.bot_token is None
    assert settings.signature_tolerance_seconds == 300
    assert settings.event_ttl_seconds == 86_400
    assert settings.max_payload_bytes == 1_048_576
    assert settings.request_timeout_seconds == 5.0


def test_slack_settings_redact_secrets_and_normalize_allowlists() -> None:
    signing_secret = "1234567890abcdef1234567890abcdef"
    bot_token = "xoxb-secret-token"
    settings = SlackChannelSettings(
        signing_secret=signing_secret,
        bot_token=bot_token,
        workspace_id="t123abc456",
        allowed_channel_ids=["c123abc456", "d123abc456"],
    )

    rendered = repr(settings)
    dumped = settings.model_dump(mode="json")
    assert signing_secret not in rendered
    assert bot_token not in rendered
    assert dumped["signing_secret"] == "**********"
    assert dumped["bot_token"] == "**********"
    assert settings.workspace_id == "T123ABC456"
    assert settings.allowed_channel_ids == ("C123ABC456", "D123ABC456")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "channels/slack"),
        ("path", "/channels/{provider}"),
        ("signing_secret", "too-short"),
        ("signing_secret", "  1234567890abcdef1234567890abcdef"),
        ("bot_token", "  "),
        ("bot_token", "secret-token"),
        ("workspace_id", "workspace"),
        ("allowed_channel_ids", ["invalid"]),
        ("allowed_channel_ids", ["C123ABC456", "c123abc456"]),
        ("signature_tolerance_seconds", 0),
        ("event_ttl_seconds", 0),
        ("max_payload_bytes", 0),
        ("request_timeout_seconds", 0),
    ],
)
def test_slack_settings_reject_invalid_security_boundaries(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        SlackChannelSettings.model_validate({field: value})
