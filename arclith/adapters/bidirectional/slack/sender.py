from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from arclith.adapters.bidirectional.slack.models import SlackPostMessageResponse
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelRateLimited,
    ChannelUnauthorized,
    ChannelUnavailable,
)
from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelOutgoingMessage,
)
from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.infrastructure.settings.channel import SlackChannelSettings

if TYPE_CHECKING:
    import httpx

_CHAT_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_AUTH_ERRORS = {
    "account_inactive",
    "invalid_auth",
    "missing_scope",
    "not_authed",
    "token_revoked",
}
_RATE_LIMIT_ERRORS = {"rate_limited", "ratelimited"}
_UNAVAILABLE_ERRORS = {
    "fatal_error",
    "internal_error",
    "request_timeout",
    "service_unavailable",
}


class SlackChannelSender(ChannelSender):
    """Send text responses through Slack ``chat.postMessage`` without an SDK."""

    def __init__(
        self,
        settings: SlackChannelSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.bot_token is None:
            raise ValueError("slack bot_token is required for outbound messages")
        self._settings = settings
        self._client = client
        self._httpx = _require_httpx() if client is None else None

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        _validate_message(message)
        if (
            self._settings.allowed_channel_ids
            and message.conversation_id not in self._settings.allowed_channel_ids
        ):
            raise ChannelUnauthorized("Slack outbound channel is not allowed")
        if self._client is not None:
            return await self._send_with_client(self._client, message)

        httpx = self._httpx
        if httpx is None:  # pragma: no cover - guarded by constructor
            raise RuntimeError("slack HTTP client is not initialized")
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            return await self._send_with_client(client, message)

    async def _send_with_client(
        self,
        client: httpx.AsyncClient,
        message: ChannelOutgoingMessage,
    ) -> ChannelDeliveryReceipt:
        token = self._settings.bot_token
        if token is None:  # pragma: no cover - guarded by constructor
            raise RuntimeError("slack bot token is not initialized")
        response = await self._post_message(client, message, token.get_secret_value())
        parsed = _parse_response(response)
        if not parsed.ok:
            _raise_api_error(parsed.error, response.headers.get("Retry-After"))
        return _delivery_receipt(message, parsed)

    async def _post_message(
        self,
        client: httpx.AsyncClient,
        message: ChannelOutgoingMessage,
        token: str,
    ) -> httpx.Response:
        httpx = self._httpx or _require_httpx()
        payload = {
            "channel": message.conversation_id,
            "text": message.text,
            "client_msg_id": message.message_id,
        }
        if message.thread_id is not None:
            payload["thread_ts"] = message.thread_id
        try:
            response = await client.post(
                _CHAT_POST_MESSAGE_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=False,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise ChannelUnavailable("Slack Web API is unavailable") from error

        _raise_for_http_status(response)
        return response


def _validate_message(message: ChannelOutgoingMessage) -> None:
    if message.channel != "slack":
        raise ChannelDeliveryFailed(
            "slack sender only accepts messages targeting the slack channel"
        )
    if message.text is None or message.attachments:
        raise ChannelDeliveryFailed(
            "slack sender v1 requires text and does not support outbound attachments"
        )
    if len(message.text) > 40_000:
        raise ChannelDeliveryFailed("slack sender text exceeds the provider limit")


def _parse_response(response: httpx.Response) -> SlackPostMessageResponse:
    try:
        return SlackPostMessageResponse.model_validate(response.json())
    except (ValueError, ValidationError) as error:
        raise ChannelDeliveryFailed(
            "Slack Web API returned an invalid response"
        ) from error


def _raise_for_http_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise ChannelRateLimited(
            "Slack Web API rate limit exceeded",
            retry_after_seconds=_retry_after_seconds(
                response.headers.get("Retry-After")
            ),
        )
    if response.status_code >= 500:
        raise ChannelUnavailable("Slack Web API is unavailable")
    if not 200 <= response.status_code < 300:
        raise ChannelDeliveryFailed("Slack Web API rejected the message")


def _delivery_receipt(
    message: ChannelOutgoingMessage,
    response: SlackPostMessageResponse,
) -> ChannelDeliveryReceipt:
    if response.ts is None:
        raise ChannelDeliveryFailed("Slack Web API omitted the message timestamp")
    return ChannelDeliveryReceipt(
        message_id=message.message_id,
        provider_message_id=response.ts,
        status="delivered",
        timestamp=datetime.now(timezone.utc),
        metadata={"channel_id": response.channel or message.conversation_id},
    )


def _raise_api_error(error: str | None, retry_after: str | None) -> None:
    if error in _AUTH_ERRORS:
        raise ChannelUnauthorized("Slack Web API authentication failed")
    if error in _RATE_LIMIT_ERRORS:
        raise ChannelRateLimited(
            "Slack Web API rate limit exceeded",
            retry_after_seconds=_retry_after_seconds(retry_after),
        )
    if error in _UNAVAILABLE_ERRORS:
        raise ChannelUnavailable("Slack Web API is unavailable")
    raise ChannelDeliveryFailed("Slack Web API rejected the message")


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _require_httpx() -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "The channel extra is required for Slack: pip install 'arclith[channel]'"
        ) from exc
    return httpx
