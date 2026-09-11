from arclith.adapters.bidirectional.webhook.adapter import WebhookChannelAdapter
from arclith.adapters.bidirectional.webhook.errors import (
    WebhookError,
    WebhookInvalidPayload,
    WebhookMissingEventId,
    WebhookPayloadTooLarge,
    WebhookResponseModeError,
    WebhookUnsupportedMediaType,
)
from arclith.adapters.bidirectional.webhook.models import (
    WebhookErrorResponse,
    WebhookIncomingPayload,
    WebhookResponse,
)
from arclith.adapters.bidirectional.webhook.security import (
    WebhookSignatureVerifier,
    sign_webhook_payload,
)
from arclith.adapters.bidirectional.webhook.sender import (
    WebhookCallbackSender,
    WebhookResponseCollector,
)

__all__ = [
    "WebhookCallbackSender",
    "WebhookChannelAdapter",
    "WebhookError",
    "WebhookErrorResponse",
    "WebhookIncomingPayload",
    "WebhookInvalidPayload",
    "WebhookMissingEventId",
    "WebhookPayloadTooLarge",
    "WebhookResponse",
    "WebhookResponseCollector",
    "WebhookResponseModeError",
    "WebhookSignatureVerifier",
    "WebhookUnsupportedMediaType",
    "build_webhook_router",
    "sign_webhook_payload",
]


def __getattr__(name: str):
    """Load the optional FastAPI router only when it is requested."""
    if name == "build_webhook_router":
        from arclith.adapters.bidirectional.webhook.fastapi import (
            build_webhook_router as _build_webhook_router,
        )

        globals()[name] = _build_webhook_router
        return _build_webhook_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
