from __future__ import annotations

from arclith.domain.models.channel import (
    ChannelDispatchResult,
    ChannelIncomingMessage,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)


class ChannelDispatcher:
    """Dispatch normalized messages without imposing an inbound transport."""

    def __init__(
        self,
        handler: ChannelMessageHandler,
        identity_resolver: ChannelIdentityResolver,
        event_store: ChannelEventStore,
        sender: ChannelSender,
        *,
        event_ttl_seconds: int = 86_400,
    ) -> None:
        if event_ttl_seconds <= 0:
            raise ValueError("channel event_ttl_seconds must be greater than zero")
        self._handler = handler
        self._identity_resolver = identity_resolver
        self._event_store = event_store
        self._sender = sender
        self._event_ttl_seconds = event_ttl_seconds

    async def dispatch(self, message: ChannelIncomingMessage) -> ChannelDispatchResult:
        claimed = await self._event_store.claim(
            message.channel,
            message.provider_event_id,
            ttl_seconds=self._event_ttl_seconds,
        )
        if not claimed:
            return ChannelDispatchResult(status="duplicate")

        try:
            identity = await self._identity_resolver.resolve(message.sender)
            handled = await self._handler.handle(message, identity)
        except BaseException:
            await self._event_store.release(
                message.channel,
                message.provider_event_id,
            )
            raise

        if handled.status == "accepted":
            return ChannelDispatchResult(status="accepted", identity=identity)

        receipts = []
        for response in handled.responses:
            receipts.append(await self._sender.send(response))
        return ChannelDispatchResult(
            status="completed",
            identity=identity,
            receipts=tuple(receipts),
        )
