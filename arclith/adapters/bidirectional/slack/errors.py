from __future__ import annotations


class SlackError(Exception):
    """Base error for Slack HTTP transport validation."""


class SlackInvalidPayload(SlackError):
    """Raised when a Slack envelope cannot be validated."""


class SlackInvalidEvent(SlackError):
    """Raised when a supported Slack event has invalid fields."""


class SlackPayloadTooLarge(SlackError):
    """Raised before buffering more than the configured request limit."""


class SlackUnsupportedMediaType(SlackError):
    """Raised when the Events API request is not JSON."""
