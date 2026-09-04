from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelRateLimited,
    ChannelUnavailable,
)
from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelOutgoingMessage,
)
from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.infrastructure.settings.channel import WebhookChannelSettings

if TYPE_CHECKING:
    import httpx


class WebhookResponseCollector(ChannelSender):
    """Collect immediate messages so the HTTP response can return them inline."""

    def __init__(self) -> None:
        self._messages: list[ChannelOutgoingMessage] = []

    @property
    def messages(self) -> tuple[ChannelOutgoingMessage, ...]:
        return tuple(self._messages)

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        _require_webhook_channel(message)
        self._messages.append(message)
        return ChannelDeliveryReceipt(
            message_id=message.message_id,
            status="accepted",
        )


class WebhookCallbackSender(ChannelSender):
    """Deliver provider-neutral responses to one server-configured callback URL."""

    def __init__(
        self,
        settings: WebhookChannelSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.response_mode != "callback" or settings.callback_url is None:
            raise ValueError(
                "webhook callback sender requires configured callback mode"
            )
        self._settings = settings
        self._callback_url = settings.callback_url
        self._client = client
        self._httpx = _require_httpx() if client is None else None

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        _require_webhook_channel(message)
        if self._client is not None:
            return await self._send_with_client(self._client, message)

        httpx = self._httpx
        if httpx is None:  # pragma: no cover - guarded by constructor
            raise RuntimeError("webhook callback HTTP client is not initialized")
        async with httpx.AsyncClient(
            timeout=self._settings.callback_timeout_seconds,
            follow_redirects=False,
        ) as client:
            return await self._send_with_client(client, message)

    async def _send_with_client(
        self,
        client: httpx.AsyncClient,
        message: ChannelOutgoingMessage,
    ) -> ChannelDeliveryReceipt:
        httpx = self._httpx or _require_httpx()
        try:
            response = await client.post(
                self._callback_url,
                json=message.model_dump(mode="json"),
                headers={"X-Arclith-Message-Id": message.message_id},
                follow_redirects=False,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise ChannelUnavailable(
                "webhook callback transport is unavailable"
            ) from error

        if response.status_code == 429:
            raise ChannelRateLimited(
                "webhook callback rate limit exceeded",
                retry_after_seconds=_retry_after_seconds(
                    response.headers.get("Retry-After")
                ),
            )
        if response.status_code >= 500:
            raise ChannelUnavailable("webhook callback endpoint is unavailable")
        if not 200 <= response.status_code < 300:
            raise ChannelDeliveryFailed("webhook callback delivery was rejected")
        return ChannelDeliveryReceipt(
            message_id=message.message_id,
            provider_message_id=_provider_message_id(
                response.headers.get("X-Arclith-Message-Id")
            ),
            status="delivered",
            timestamp=datetime.now(timezone.utc),
        )


def _require_webhook_channel(message: ChannelOutgoingMessage) -> None:
    if message.channel != "webhook":
        raise ChannelDeliveryFailed(
            "webhook sender only accepts messages targeting the webhook channel"
        )


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _provider_message_id(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _require_httpx() -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "The channel extra is required for webhook callbacks: "
            "pip install 'arclith[channel]'"
        ) from exc
    return httpx
