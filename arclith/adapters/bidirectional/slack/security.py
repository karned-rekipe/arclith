from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable, Mapping
from typing import Never

from arclith.adapters.bidirectional.webhook.security import header_value
from arclith.domain.errors.channel import InvalidChannelSignature
from arclith.infrastructure.settings.channel import SlackChannelSettings


def sign_slack_payload(secret: str, timestamp: int, body: bytes) -> str:
    """Return Slack's canonical ``v0`` request signature."""

    signed = b"v0:" + str(timestamp).encode() + b":" + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"v0={digest}"


class SlackSignatureVerifier:
    def __init__(
        self,
        settings: SlackChannelSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if settings.signing_secret is None:
            raise ValueError("slack signing_secret is required for Events API requests")
        self._settings = settings
        self._clock = clock

    def verify(self, body: bytes, headers: Mapping[str, str]) -> None:
        raw_timestamp = header_value(headers, "X-Slack-Request-Timestamp")
        signature = header_value(headers, "X-Slack-Signature")
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

        secret = self._settings.signing_secret
        if secret is None:  # pragma: no cover - guarded by constructor
            raise RuntimeError("slack signing secret is not initialized")
        expected = sign_slack_payload(secret.get_secret_value(), timestamp, body)
        if signature is None or not hmac.compare_digest(signature, expected):
            self._reject()

    @staticmethod
    def _reject() -> Never:
        raise InvalidChannelSignature("Slack signature is missing, stale, or invalid")
