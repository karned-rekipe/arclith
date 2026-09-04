from arclith.domain.errors.channel import ChannelError


class WebhookError(ChannelError):
    """Base error for generic webhook transport validation."""


class WebhookPayloadTooLarge(WebhookError):
    """Raised before parsing a body that exceeds the configured limit."""


class WebhookUnsupportedMediaType(WebhookError):
    """Raised when the inbound payload is not JSON."""


class WebhookInvalidPayload(WebhookError):
    """Raised when the authenticated body cannot satisfy the webhook schema."""


class WebhookMissingEventId(WebhookError):
    """Raised when the configured stable event ID header is absent or blank."""


class WebhookResponseModeError(WebhookError):
    """Raised when handler completion contradicts the configured response mode."""
