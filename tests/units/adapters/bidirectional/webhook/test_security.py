from __future__ import annotations

import pytest

from arclith.adapters.bidirectional.webhook import (
    WebhookSignatureVerifier,
    sign_webhook_payload,
)
from arclith.domain.errors.channel import InvalidChannelSignature
from arclith.infrastructure.settings.channel import WebhookChannelSettings

_SECRET = "a-secure-webhook-secret-with-32-bytes"
_BODY = b'{"text":"bonjour"}'


def _settings() -> WebhookChannelSettings:
    return WebhookChannelSettings(secret=_SECRET)


def test_signature_verifier_accepts_canonical_signature_case_insensitively() -> None:
    verifier = WebhookSignatureVerifier(_settings(), clock=lambda: 1_000.0)

    verifier.verify(
        _BODY,
        {
            "x-arclith-timestamp": "1000",
            "x-arclith-signature": sign_webhook_payload(_SECRET, 1_000, _BODY),
        },
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Arclith-Timestamp": "not-an-integer"},
        {
            "X-Arclith-Timestamp": "1000",
            "X-Arclith-Signature": "sha256=wrong",
        },
        {
            "X-Arclith-Timestamp": "-1",
            "X-Arclith-Signature": "sha256=wrong",
        },
        {
            "X-Arclith-Timestamp": "699",
            "X-Arclith-Signature": sign_webhook_payload(_SECRET, 699, _BODY),
        },
    ],
)
def test_signature_verifier_rejects_missing_invalid_or_stale_requests(
    headers: dict[str, str],
) -> None:
    verifier = WebhookSignatureVerifier(_settings(), clock=lambda: 1_000.0)

    with pytest.raises(InvalidChannelSignature, match="missing, stale, or invalid"):
        verifier.verify(_BODY, headers)


def test_signature_verifier_is_disabled_when_no_secret_is_configured() -> None:
    WebhookSignatureVerifier(WebhookChannelSettings()).verify(_BODY, {})
