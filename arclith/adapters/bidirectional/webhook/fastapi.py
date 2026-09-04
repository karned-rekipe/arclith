from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from arclith.adapters.bidirectional.webhook.adapter import WebhookChannelAdapter
from arclith.adapters.bidirectional.webhook.errors import (
    WebhookInvalidPayload,
    WebhookMissingEventId,
    WebhookPayloadTooLarge,
    WebhookResponseModeError,
    WebhookUnsupportedMediaType,
)
from arclith.adapters.bidirectional.webhook.models import (
    WebhookErrorResponse,
    WebhookResponse,
)
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelIdentityNotResolved,
    ChannelRateLimited,
    ChannelUnauthorized,
    ChannelUnavailable,
    InvalidChannelSignature,
    UnsupportedChannelEvent,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)
from arclith.infrastructure.settings.channel import WebhookChannelSettings

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": WebhookErrorResponse, "description": "Missing event identifier"},
    401: {"model": WebhookErrorResponse, "description": "Invalid webhook signature"},
    403: {
        "model": WebhookErrorResponse,
        "description": "Unresolved or unauthorized identity",
    },
    413: {"model": WebhookErrorResponse, "description": "Payload too large"},
    415: {"model": WebhookErrorResponse, "description": "Unsupported media type"},
    422: {"model": WebhookErrorResponse, "description": "Invalid webhook event"},
    429: {"model": WebhookErrorResponse, "description": "Callback rate limited"},
    500: {
        "model": WebhookErrorResponse,
        "description": "Invalid response-mode contract",
    },
    502: {"model": WebhookErrorResponse, "description": "Callback rejected"},
    503: {"model": WebhookErrorResponse, "description": "Callback unavailable"},
}

_KNOWN_ERRORS: tuple[tuple[type[Exception], int, str, str], ...] = (
    (WebhookMissingEventId, 400, "missing_event_id", "Webhook event ID is required"),
    (InvalidChannelSignature, 401, "invalid_signature", "Webhook signature is invalid"),
    (
        ChannelIdentityNotResolved,
        403,
        "identity_not_resolved",
        "Channel identity is not mapped",
    ),
    (
        ChannelUnauthorized,
        403,
        "channel_unauthorized",
        "Channel identity is not authorized",
    ),
    (WebhookPayloadTooLarge, 413, "payload_too_large", "Webhook payload is too large"),
    (
        WebhookUnsupportedMediaType,
        415,
        "unsupported_media_type",
        "Webhook payload must be JSON",
    ),
    (WebhookInvalidPayload, 422, "invalid_payload", "Webhook payload is invalid"),
    (UnsupportedChannelEvent, 422, "unsupported_event", "Webhook event is unsupported"),
    (
        WebhookResponseModeError,
        500,
        "response_mode_error",
        "Webhook handler result violates configured response mode",
    ),
    (ChannelDeliveryFailed, 502, "callback_rejected", "Webhook callback was rejected"),
    (
        ChannelUnavailable,
        503,
        "callback_unavailable",
        "Webhook callback is unavailable",
    ),
)


def build_webhook_router(
    settings: WebhookChannelSettings,
    handler: ChannelMessageHandler,
    identity_resolver: ChannelIdentityResolver,
    event_store: ChannelEventStore,
    *,
    callback_sender: ChannelSender | None = None,
    tags: Sequence[str] = ("channel-webhook",),
) -> APIRouter:
    """Build a reusable FastAPI router for the configured generic webhook path."""

    adapter = WebhookChannelAdapter(
        settings,
        handler,
        identity_resolver,
        event_store,
        callback_sender=callback_sender,
    )
    router = APIRouter(tags=list(tags))

    @router.post(
        settings.path,
        response_model=WebhookResponse,
        status_code=status.HTTP_200_OK,
        responses={
            202: {
                "model": WebhookResponse,
                "description": "Durable processing accepted",
            },
            **_ERROR_RESPONSES,
        },
    )
    async def receive_webhook(request: Request) -> JSONResponse:
        try:
            body = await _read_limited_body(request, settings.max_payload_bytes)
            response = await adapter.dispatch(body, request.headers)
        except Exception as error:
            mapped = _map_error(error)
            if mapped is None:
                raise
            return mapped
        response_status = 202 if response.status == "accepted" else 200
        return JSONResponse(
            status_code=response_status,
            content=response.model_dump(mode="json"),
        )

    return router


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise WebhookPayloadTooLarge("webhook payload exceeds configured limit")
    return bytes(body)


def _map_error(error: Exception) -> JSONResponse | None:
    if isinstance(error, ChannelRateLimited):
        headers = _retry_after_header(error.retry_after_seconds)
        return _error_response(
            429,
            "callback_rate_limited",
            "Webhook callback is rate limited",
            headers=headers,
        )
    for error_type, status_code, code, detail in _KNOWN_ERRORS:
        if isinstance(error, error_type):
            return _error_response(status_code, code, detail)
    return None


def _error_response(
    status_code: int,
    code: str,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = WebhookErrorResponse(code=code, detail=detail)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def _retry_after_header(seconds: float | None) -> dict[str, str] | None:
    if seconds is None:
        return None
    return {"Retry-After": str(math.ceil(seconds))}
