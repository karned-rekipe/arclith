from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import JsonValue, ValidationError

from arclith.adapters.bidirectional.slack.errors import (
    SlackInvalidEvent,
    SlackInvalidPayload,
    SlackPayloadTooLarge,
    SlackUnsupportedMediaType,
)
from arclith.adapters.bidirectional.slack.models import (
    SlackChallengeResponse,
    SlackEnvelope,
    SlackEventCallbackPayload,
    SlackEventResponse,
    SlackFilePayload,
    SlackMessageEvent,
    SlackUrlVerificationPayload,
)
from arclith.adapters.bidirectional.slack.security import SlackSignatureVerifier
from arclith.adapters.bidirectional.slack.sender import SlackChannelSender
from arclith.adapters.bidirectional.webhook.security import header_value
from arclith.application.channel import ChannelDispatcher
from arclith.domain.errors.channel import ChannelUnauthorized
from arclith.domain.models.channel import (
    ChannelAttachment,
    ChannelIdentity,
    ChannelIncomingMessage,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)
from arclith.infrastructure.settings.channel import SlackChannelSettings

SlackAdapterResponse = SlackChallengeResponse | SlackEventResponse
_SUPPORTED_MESSAGE_SUBTYPES = {None, "file_share"}
_SLACK_RETRY_REASONS = {
    "connection_failed",
    "http_error",
    "http_timeout",
    "ssl_error",
    "too_many_redirects",
    "unknown_error",
}


class SlackChannelAdapter:
    """Authenticate, normalize and dispatch Slack Events API envelopes."""

    def __init__(
        self,
        settings: SlackChannelSettings,
        handler: ChannelMessageHandler,
        identity_resolver: ChannelIdentityResolver,
        event_store: ChannelEventStore,
        *,
        sender: ChannelSender | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._handler = handler
        self._identity_resolver = identity_resolver
        self._event_store = event_store
        self._sender = sender or SlackChannelSender(settings)
        verifier_options = {} if clock is None else {"clock": clock}
        self._signature_verifier = SlackSignatureVerifier(
            settings,
            **verifier_options,
        )

    async def dispatch(
        self,
        body: bytes,
        headers: Mapping[str, str],
    ) -> SlackAdapterResponse:
        self._validate_size(body)
        self._validate_content_type(headers)
        self._signature_verifier.verify(body, headers)
        envelope = self._parse_envelope(body)
        if envelope.type == "url_verification":
            return self._challenge(body)
        if envelope.type != "event_callback":
            return SlackEventResponse(status="ignored")

        callback = self._event_callback(body)
        self._validate_workspace(callback.team_id)
        event = self._message_event(callback.event)
        if event is None or self._must_ignore(event):
            return SlackEventResponse(status="ignored")
        self._validate_channel(event.channel)
        message = self._normalize(callback, event, headers)
        if message is None:
            return SlackEventResponse(status="ignored")

        result = await ChannelDispatcher(
            self._handler,
            self._identity_resolver,
            self._event_store,
            self._sender,
            event_ttl_seconds=self._settings.event_ttl_seconds,
        ).dispatch(message)
        return SlackEventResponse(status=result.status, receipts=result.receipts)

    def _validate_size(self, body: bytes) -> None:
        if len(body) > self._settings.max_payload_bytes:
            raise SlackPayloadTooLarge("Slack payload exceeds configured limit")

    @staticmethod
    def _validate_content_type(headers: Mapping[str, str]) -> None:
        content_type = (header_value(headers, "Content-Type") or "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            raise SlackUnsupportedMediaType("Slack Events API payload must be JSON")

    @staticmethod
    def _parse_envelope(body: bytes) -> SlackEnvelope:
        try:
            return SlackEnvelope.model_validate_json(body)
        except ValidationError as error:
            raise SlackInvalidPayload("Slack envelope is invalid") from error

    @staticmethod
    def _challenge(body: bytes) -> SlackChallengeResponse:
        try:
            payload = SlackUrlVerificationPayload.model_validate_json(body)
        except ValidationError as error:
            raise SlackInvalidPayload(
                "Slack URL verification payload is invalid"
            ) from error
        return SlackChallengeResponse(challenge=payload.challenge)

    @staticmethod
    def _event_callback(body: bytes) -> SlackEventCallbackPayload:
        try:
            return SlackEventCallbackPayload.model_validate_json(body)
        except ValidationError as error:
            raise SlackInvalidEvent(
                "Slack event callback payload is invalid"
            ) from error

    @staticmethod
    def _message_event(event: dict[str, JsonValue]) -> SlackMessageEvent | None:
        if event.get("type") not in {"message", "app_mention"}:
            return None
        try:
            return SlackMessageEvent.model_validate(event)
        except ValidationError as error:
            raise SlackInvalidEvent("Slack message event is invalid") from error

    @staticmethod
    def _must_ignore(event: SlackMessageEvent) -> bool:
        return (
            event.user is None
            or event.bot_id is not None
            or event.app_id is not None
            or event.subtype not in _SUPPORTED_MESSAGE_SUBTYPES
        )

    def _validate_workspace(self, team_id: str) -> None:
        if (
            self._settings.workspace_id is not None
            and team_id != self._settings.workspace_id
        ):
            raise ChannelUnauthorized("Slack workspace is not allowed")

    def _validate_channel(self, channel_id: str) -> None:
        allowed = self._settings.allowed_channel_ids
        if allowed and channel_id not in allowed:
            raise ChannelUnauthorized("Slack channel is not allowed")

    def _normalize(
        self,
        callback: SlackEventCallbackPayload,
        event: SlackMessageEvent,
        headers: Mapping[str, str],
    ) -> ChannelIncomingMessage | None:
        text = _normalized_text(event.text)
        attachments = tuple(self._attachment(file) for file in event.files)
        if text is None and not attachments:
            return None
        user_id = event.user
        if user_id is None:  # pragma: no cover - guarded by _must_ignore
            return None
        return ChannelIncomingMessage(
            channel="slack",
            provider_event_id=callback.event_id,
            conversation_id=event.channel,
            thread_id=event.thread_ts or event.ts,
            sender=ChannelIdentity(
                provider="slack",
                external_user_id=user_id,
                external_tenant_id=callback.enterprise_id or callback.team_id,
                external_workspace_id=callback.team_id,
            ),
            text=text,
            attachments=attachments,
            metadata=_event_metadata(event, headers),
        )

    @staticmethod
    def _attachment(file: SlackFilePayload) -> ChannelAttachment:
        url = file.url_private_download or file.url_private
        if url is None:
            raise SlackInvalidEvent("Slack file is missing a private URL")
        try:
            return ChannelAttachment(
                kind="slack_file",
                name=file.name,
                content_type=file.mimetype,
                url=url,
                size=file.size,
                metadata={"slack_file_id": file.id},
            )
        except ValidationError as error:
            raise SlackInvalidEvent("Slack file payload is invalid") from error


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _event_metadata(
    event: SlackMessageEvent,
    headers: Mapping[str, str],
) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {
        "event_type": event.type,
        "event_ts": event.event_ts or event.ts,
    }
    retry_num = header_value(headers, "X-Slack-Retry-Num")
    retry_reason = header_value(headers, "X-Slack-Retry-Reason")
    if _valid_retry_number(retry_num):
        metadata["retry_num"] = retry_num
    if retry_reason in _SLACK_RETRY_REASONS:
        metadata["retry_reason"] = retry_reason
    return metadata


def _valid_retry_number(value: str | None) -> bool:
    return value is not None and len(value) <= 3 and value.isascii() and value.isdigit()
