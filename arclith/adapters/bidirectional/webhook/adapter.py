from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import ValidationError

from arclith.adapters.bidirectional.webhook.errors import (
    WebhookInvalidPayload,
    WebhookMissingEventId,
    WebhookPayloadTooLarge,
    WebhookResponseModeError,
    WebhookUnsupportedMediaType,
)
from arclith.adapters.bidirectional.webhook.models import (
    WebhookIncomingPayload,
    WebhookResponse,
)
from arclith.adapters.bidirectional.webhook.security import (
    WebhookSignatureVerifier,
    header_value,
)
from arclith.adapters.bidirectional.webhook.sender import (
    WebhookCallbackSender,
    WebhookResponseCollector,
)
from arclith.application.channel import ChannelDispatcher
from arclith.domain.models.channel import ChannelIdentity, ChannelIncomingMessage
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)
from arclith.infrastructure.settings.channel import WebhookChannelSettings


class WebhookChannelAdapter:
    """Authenticate, normalize and dispatch one generic HTTP webhook event."""

    def __init__(
        self,
        settings: WebhookChannelSettings,
        handler: ChannelMessageHandler,
        identity_resolver: ChannelIdentityResolver,
        event_store: ChannelEventStore,
        *,
        callback_sender: ChannelSender | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._handler = handler
        self._identity_resolver = identity_resolver
        self._event_store = event_store
        self._callback_sender = callback_sender
        verifier_options = {} if clock is None else {"clock": clock}
        self._signature_verifier = WebhookSignatureVerifier(
            settings,
            **verifier_options,
        )

    async def dispatch(
        self,
        body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookResponse:
        self._validate_size(body)
        self._validate_content_type(headers)
        self._signature_verifier.verify(body, headers)
        event_id = self._event_id(headers)
        message = self._normalize(body, event_id)
        collector, sender = self._sender()
        result = await ChannelDispatcher(
            self._handler,
            self._identity_resolver,
            self._event_store,
            sender,
            event_ttl_seconds=self._settings.event_ttl_seconds,
        ).dispatch(message)
        self._validate_result_mode(result.status)
        return WebhookResponse(
            status=result.status,
            responses=collector.messages if collector is not None else (),
            receipts=result.receipts,
        )

    def _validate_size(self, body: bytes) -> None:
        if len(body) > self._settings.max_payload_bytes:
            raise WebhookPayloadTooLarge("webhook payload exceeds configured limit")

    @staticmethod
    def _validate_content_type(headers: Mapping[str, str]) -> None:
        content_type = (header_value(headers, "Content-Type") or "").split(";", 1)[0]
        media_type = content_type.strip().lower()
        if media_type != "application/json" and not media_type.endswith("+json"):
            raise WebhookUnsupportedMediaType(
                "webhook payload must use a JSON media type"
            )

    def _event_id(self, headers: Mapping[str, str]) -> str:
        event_id = (
            header_value(headers, self._settings.idempotency_header) or ""
        ).strip()
        if not event_id:
            raise WebhookMissingEventId("webhook event ID header is required")
        return event_id

    def _normalize(self, body: bytes, event_id: str) -> ChannelIncomingMessage:
        try:
            payload = WebhookIncomingPayload.model_validate_json(body)
            metadata = {
                name: payload.metadata[name]
                for name in self._settings.metadata_allowlist
                if name in payload.metadata
            }
            return ChannelIncomingMessage(
                channel="webhook",
                provider_event_id=event_id,
                conversation_id=payload.conversation_id,
                thread_id=payload.thread_id,
                sender=ChannelIdentity(
                    provider="webhook",
                    external_user_id=payload.sender_id,
                    display_name=payload.sender_display_name,
                    external_tenant_id=payload.external_tenant_id,
                    external_workspace_id=payload.external_workspace_id,
                ),
                text=payload.text,
                attachments=payload.attachments,
                metadata=metadata,
            )
        except ValidationError as error:
            raise WebhookInvalidPayload(
                "webhook payload does not match the expected schema"
            ) from error

    def _sender(self) -> tuple[WebhookResponseCollector | None, ChannelSender]:
        if self._settings.response_mode != "callback":
            collector = WebhookResponseCollector()
            return collector, collector
        sender = self._callback_sender or WebhookCallbackSender(self._settings)
        return None, sender

    def _validate_result_mode(self, status: str) -> None:
        if status == "duplicate":
            return
        if self._settings.response_mode == "sync" and status != "completed":
            raise WebhookResponseModeError(
                "sync webhook mode requires a completed handler result"
            )
        if self._settings.response_mode == "accepted" and status != "accepted":
            raise WebhookResponseModeError(
                "accepted webhook mode requires a durable accepted handler result"
            )
