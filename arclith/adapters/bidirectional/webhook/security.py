from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable, Mapping
from typing import Never

from arclith.domain.errors.channel import InvalidChannelSignature
from arclith.infrastructure.settings.channel import WebhookChannelSettings


def sign_webhook_payload(secret: str, timestamp: int, body: bytes) -> str:
    """Return the canonical timestamped HMAC header value."""

    signed = str(timestamp).encode() + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Read a header case-insensitively from generic mappings and Starlette Headers."""

    direct = headers.get(name)
    if direct is not None:
        return direct
    expected = name.lower()
    return next(
        (value for key, value in headers.items() if key.lower() == expected), None
    )


class WebhookSignatureVerifier:
    def __init__(
        self,
        settings: WebhookChannelSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._clock = clock

    def verify(self, body: bytes, headers: Mapping[str, str]) -> None:
        secret = self._settings.secret
        if secret is None:
            return
        secret_value = secret.get_secret_value()

        raw_timestamp = header_value(headers, self._settings.timestamp_header)
        signature = header_value(headers, self._settings.signature_header)
        try:
            timestamp = int(raw_timestamp or "")
        except ValueError:
            self._reject()
        if (
            timestamp < 0
            or abs(self._clock() - timestamp)
            > self._settings.signature_tolerance_seconds
        ):
            self._reject()

        expected = sign_webhook_payload(secret_value, timestamp, body)
        if signature is None or not hmac.compare_digest(signature, expected):
            self._reject()

    @staticmethod
    def _reject() -> Never:
        raise InvalidChannelSignature("Webhook signature is missing, stale, or invalid")
