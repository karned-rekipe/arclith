from __future__ import annotations

import pytest

from arclith.adapters.bidirectional.slack import (
    SlackSignatureVerifier,
    sign_slack_payload,
)
from arclith.domain.errors.channel import InvalidChannelSignature
from arclith.infrastructure.settings.channel import SlackChannelSettings

_SECRET = "1234567890abcdef1234567890abcdef"
_BODY = b'{"type":"event_callback"}'


def _settings() -> SlackChannelSettings:
    return SlackChannelSettings(signing_secret=_SECRET)


def test_signature_verifier_accepts_slack_v0_signature_case_insensitively() -> None:
    verifier = SlackSignatureVerifier(_settings(), clock=lambda: 1_000.0)

    verifier.verify(
        _BODY,
        {
            "x-slack-request-timestamp": "1000",
            "x-slack-signature": sign_slack_payload(_SECRET, 1_000, _BODY),
        },
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Slack-Request-Timestamp": "not-an-integer"},
        {
            "X-Slack-Request-Timestamp": "1000",
            "X-Slack-Signature": "v0=wrong",
        },
        {
            "X-Slack-Request-Timestamp": "-1",
            "X-Slack-Signature": "v0=wrong",
        },
        {
            "X-Slack-Request-Timestamp": "699",
            "X-Slack-Signature": sign_slack_payload(_SECRET, 699, _BODY),
        },
    ],
)
def test_signature_verifier_rejects_missing_invalid_or_stale_requests(
    headers: dict[str, str],
) -> None:
    verifier = SlackSignatureVerifier(_settings(), clock=lambda: 1_000.0)

    with pytest.raises(InvalidChannelSignature, match="missing, stale, or invalid"):
        verifier.verify(_BODY, headers)


def test_signature_verifier_requires_a_configured_secret() -> None:
    with pytest.raises(ValueError, match="signing_secret is required"):
        SlackSignatureVerifier(SlackChannelSettings())
