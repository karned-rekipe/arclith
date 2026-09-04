from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from arclith.adapters.bidirectional.slack.adapter import SlackChannelAdapter
from arclith.adapters.bidirectional.slack.errors import (
    SlackInvalidEvent,
    SlackInvalidPayload,
    SlackPayloadTooLarge,
    SlackUnsupportedMediaType,
)
from arclith.adapters.bidirectional.slack.models import (
    SlackChallengeResponse,
    SlackErrorResponse,
    SlackEventResponse,
)
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelIdentityNotResolved,
    ChannelRateLimited,
    ChannelUnauthorized,
    ChannelUnavailable,
    InvalidChannelSignature,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)
from arclith.infrastructure.settings.channel import SlackChannelSettings

_SUCCESS_MODEL = SlackChallengeResponse | SlackEventResponse
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": SlackErrorResponse, "description": "Invalid Slack envelope"},
    401: {"model": SlackErrorResponse, "description": "Invalid Slack signature"},
    403: {
        "model": SlackErrorResponse,
        "description": "Unresolved or unauthorized Slack identity",
    },
    413: {"model": SlackErrorResponse, "description": "Payload too large"},
    415: {"model": SlackErrorResponse, "description": "Unsupported media type"},
    422: {"model": SlackErrorResponse, "description": "Invalid Slack event"},
    429: {"model": SlackErrorResponse, "description": "Slack API rate limited"},
    502: {"model": SlackErrorResponse, "description": "Slack API rejected message"},
    503: {"model": SlackErrorResponse, "description": "Slack API unavailable"},
}

_KNOWN_ERRORS: tuple[tuple[type[Exception], int, str, str], ...] = (
    (SlackInvalidPayload, 400, "invalid_payload", "Slack payload is invalid"),
    (InvalidChannelSignature, 401, "invalid_signature", "Slack signature is invalid"),
    (
        ChannelIdentityNotResolved,
        403,
        "identity_not_resolved",
        "Slack identity is not mapped",
    ),
    (
        ChannelUnauthorized,
        403,
        "channel_unauthorized",
        "Slack workspace, channel, or credentials are not authorized",
    ),
    (SlackPayloadTooLarge, 413, "payload_too_large", "Slack payload is too large"),
    (
        SlackUnsupportedMediaType,
        415,
        "unsupported_media_type",
        "Slack payload must be JSON",
    ),
    (SlackInvalidEvent, 422, "invalid_event", "Slack event is invalid"),
    (ChannelDeliveryFailed, 502, "delivery_failed", "Slack delivery was rejected"),
    (ChannelUnavailable, 503, "slack_unavailable", "Slack API is unavailable"),
)


def build_slack_router(
    settings: SlackChannelSettings,
    handler: ChannelMessageHandler,
    identity_resolver: ChannelIdentityResolver,
    event_store: ChannelEventStore,
    *,
    sender: ChannelSender | None = None,
    tags: Sequence[str] = ("channel-slack",),
) -> APIRouter:
    """Build a FastAPI router for Slack Events API HTTP delivery."""

    adapter = SlackChannelAdapter(
        settings,
        handler,
        identity_resolver,
        event_store,
        sender=sender,
    )
    router = APIRouter(tags=list(tags))

    @router.post(
        settings.path,
        response_model=_SUCCESS_MODEL,
        status_code=status.HTTP_200_OK,
        responses=_ERROR_RESPONSES,
    )
    async def receive_slack_event(request: Request) -> JSONResponse:
        try:
            body = await _read_limited_body(request, settings.max_payload_bytes)
            response = await adapter.dispatch(body, request.headers)
        except Exception as error:
            mapped = _map_error(error)
            if mapped is None:
                raise
            return mapped
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=response.model_dump(mode="json"),
        )

    return router


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise SlackPayloadTooLarge("Slack payload exceeds configured limit")
    return bytes(body)


def _map_error(error: Exception) -> JSONResponse | None:
    if isinstance(error, ChannelRateLimited):
        return _error_response(
            429,
            "slack_rate_limited",
            "Slack API is rate limited",
            headers=_retry_after_header(error.retry_after_seconds),
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
    body = SlackErrorResponse(code=code, detail=detail)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def _retry_after_header(seconds: float | None) -> dict[str, str] | None:
    if seconds is None:
        return None
    return {"Retry-After": str(math.ceil(seconds))}
