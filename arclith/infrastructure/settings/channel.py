from __future__ import annotations

import ipaddress
import re
from typing import Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import (
    PositiveFloat,
    PositiveInt,
    SecretStr,
    field_validator,
    model_validator,
)

from arclith.infrastructure.settings._base import SettingsModel

WebhookResponseMode = Literal["sync", "accepted", "callback"]
_HTTP_HEADER_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_HOST_LABEL_PATTERN = re.compile(r"^[0-9A-Za-z](?:[0-9A-Za-z-]{0,61}[0-9A-Za-z])?$")
_SLACK_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{8,}$")


def _validate_callback_port(parsed: SplitResult) -> None:
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("webhook callback_url port must be valid") from error


def _has_unsafe_callback_url_parts(parsed: SplitResult, value: str) -> bool:
    return (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or any(character.isspace() for character in value)
    )


class MemoryChannelSettings(SettingsModel):
    """Dependency-free channel adapter settings for tests and local POCs."""

    enabled: bool = True


class WebhookChannelSettings(SettingsModel):
    """Secure-by-default generic HTTP webhook settings."""

    enabled: bool = True
    path: str = "/channels/webhook"
    secret: SecretStr | None = None
    signature_header: str = "X-Arclith-Signature"
    timestamp_header: str = "X-Arclith-Timestamp"
    signature_tolerance_seconds: PositiveInt = 300
    idempotency_header: str = "X-Arclith-Event-Id"
    event_ttl_seconds: PositiveInt = 86_400
    max_payload_bytes: PositiveInt = 1_048_576
    metadata_allowlist: tuple[str, ...] = ()
    response_mode: WebhookResponseMode = "sync"
    callback_url: str | None = None
    callback_allowed_host: str | None = None
    callback_timeout_seconds: PositiveFloat = 5.0

    @field_validator("path")
    @classmethod
    def path_must_be_static_and_absolute(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value == "/"
            or value.endswith("/")
            or "//" in value
            or any(character in value for character in "{}?#")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("webhook path must be a static absolute route")
        return value

    @field_validator("signature_header", "timestamp_header", "idempotency_header")
    @classmethod
    def headers_must_be_http_tokens(cls, value: str) -> str:
        normalized = value.strip()
        if not _HTTP_HEADER_PATTERN.fullmatch(normalized):
            raise ValueError("webhook header names must be valid HTTP tokens")
        return normalized

    @field_validator("secret")
    @classmethod
    def secret_must_be_strong_when_configured(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        secret_value = value.get_secret_value()
        if len(secret_value.encode()) < 32 or not secret_value.strip():
            raise ValueError("webhook secret must contain at least 32 bytes")
        return value

    @field_validator("metadata_allowlist")
    @classmethod
    def metadata_allowlist_must_be_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized) or len(set(normalized)) != len(
            normalized
        ):
            raise ValueError("webhook metadata_allowlist must contain unique names")
        return normalized

    @field_validator("callback_allowed_host")
    @classmethod
    def callback_allowed_host_must_be_exact(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().rstrip(".")
        if not normalized:
            raise ValueError("webhook callback_allowed_host must be an exact hostname")
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            labels = normalized.split(".")
            if (
                len(normalized) > 253
                or any(not _HOST_LABEL_PATTERN.fullmatch(label) for label in labels)
                or normalized == "localhost"
                or normalized.endswith(".localhost")
            ):
                raise ValueError(
                    "webhook callback_allowed_host must be an exact public hostname"
                ) from None
            return normalized
        if not address.is_global:
            raise ValueError("webhook callback IP address must be globally routable")
        return normalized

    @field_validator("callback_url")
    @classmethod
    def callback_url_must_be_safe_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlsplit(normalized)
        _validate_callback_port(parsed)
        if _has_unsafe_callback_url_parts(parsed, normalized):
            raise ValueError(
                "webhook callback_url must be a credential-free HTTPS URL "
                "without query or fragment"
            )
        return normalized

    @model_validator(mode="after")
    def validate_composition(self) -> "WebhookChannelSettings":
        headers = {
            self.signature_header.lower(),
            self.timestamp_header.lower(),
            self.idempotency_header.lower(),
        }
        if len(headers) != 3:
            raise ValueError(
                "webhook signature, timestamp and idempotency headers must differ"
            )
        if self.response_mode != "callback":
            if self.callback_url is not None or self.callback_allowed_host is not None:
                raise ValueError(
                    "webhook callback settings require response_mode=callback"
                )
            return self
        if self.callback_url is None or self.callback_allowed_host is None:
            raise ValueError(
                "webhook callback mode requires callback_url and callback_allowed_host"
            )
        callback_host = urlsplit(self.callback_url).hostname
        if (
            callback_host is None
            or callback_host.lower().rstrip(".") != self.callback_allowed_host
        ):
            raise ValueError(
                "webhook callback_url host must match callback_allowed_host"
            )
        return self


class SlackChannelSettings(SettingsModel):
    """Slack Events API and ``chat.postMessage`` settings."""

    enabled: bool = True
    path: str = "/channels/slack/events"
    signing_secret: SecretStr | None = None
    bot_token: SecretStr | None = None
    workspace_id: str | None = None
    allowed_channel_ids: tuple[str, ...] = ()
    signature_tolerance_seconds: PositiveInt = 300
    event_ttl_seconds: PositiveInt = 86_400
    max_payload_bytes: PositiveInt = 1_048_576
    request_timeout_seconds: PositiveFloat = 5.0

    @field_validator("path")
    @classmethod
    def path_must_be_static_and_absolute(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value == "/"
            or value.endswith("/")
            or "//" in value
            or any(character in value for character in "{}?#")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("slack path must be a static absolute route")
        return value

    @field_validator("signing_secret")
    @classmethod
    def signing_secret_must_be_strong_when_configured(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if len(secret.encode()) < 32 or secret != secret.strip():
            raise ValueError("slack signing_secret must contain at least 32 bytes")
        return value

    @field_validator("bot_token")
    @classmethod
    def bot_token_must_not_be_blank(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value()
        if (
            not token.startswith("xoxb-")
            or token != token.strip()
            or any(character.isspace() for character in token)
        ):
            raise ValueError("slack bot_token must be a valid xoxb token")
        return value

    @field_validator("workspace_id")
    @classmethod
    def workspace_id_must_be_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized.startswith("T") or not _SLACK_ID_PATTERN.fullmatch(
            normalized
        ):
            raise ValueError("slack workspace_id must be a valid team ID")
        return normalized

    @field_validator("allowed_channel_ids")
    @classmethod
    def allowed_channels_must_be_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip().upper() for item in value)
        if any(
            not item.startswith(("C", "D", "G"))
            or not _SLACK_ID_PATTERN.fullmatch(item)
            for item in normalized
        ) or len(set(normalized)) != len(normalized):
            raise ValueError(
                "slack allowed_channel_ids must contain unique valid channel IDs"
            )
        return normalized


class ChannelSettings(SettingsModel):
    """Configuration sections for provider-neutral channel adapters."""

    memory: MemoryChannelSettings | None = None
    webhook: WebhookChannelSettings | None = None
    slack: SlackChannelSettings | None = None

    def configured_adapters(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("memory", "webhook", "slack")
            if (settings := getattr(self, name)) is not None and settings.enabled
        )
