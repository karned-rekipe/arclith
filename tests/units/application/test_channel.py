from __future__ import annotations

import pytest

from arclith.adapters.bidirectional.memory import MemoryChannel
from arclith.application.channel import ChannelDispatcher
from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelIncomingMessage,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import (
    ChannelIdentityResolver,
    ChannelSender,
)


class StubIdentityResolver(ChannelIdentityResolver):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def resolve(self, identity: ChannelIdentity) -> ResolvedChannelIdentity:
        self.calls += 1
        if self.fail:
            raise RuntimeError("identity unavailable")
        return ResolvedChannelIdentity(user_id=f"app-{identity.external_user_id}")


class StubHandler(ChannelMessageHandler):
    def __init__(self, result: ChannelHandlerResult, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls = 0

    async def handle(
        self,
        message: ChannelIncomingMessage,
        identity: ResolvedChannelIdentity,
    ) -> ChannelHandlerResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("handler failed")
        assert identity.user_id == "app-U123"
        return self.result


class FailingSender(ChannelSender):
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        raise RuntimeError("provider failed")


def _incoming() -> ChannelIncomingMessage:
    return ChannelIncomingMessage(
        channel="slack",
        provider_event_id="Ev123",
        conversation_id="C123",
        sender=ChannelIdentity(provider="slack", external_user_id="U123"),
        text="ping",
    )


def _response() -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        channel="slack",
        conversation_id="C123",
        text="pong",
    )


async def test_channel_dispatcher_resolves_handles_and_sends_responses() -> None:
    memory = MemoryChannel()
    resolver = StubIdentityResolver()
    response = _response()
    handler = StubHandler(ChannelHandlerResult(responses=(response,)))
    dispatcher = ChannelDispatcher(handler, resolver, memory, memory)

    result = await dispatcher.dispatch(_incoming())

    assert result.status == "completed"
    assert result.identity == ResolvedChannelIdentity(user_id="app-U123")
    assert len(result.receipts) == 1
    assert result.receipts[0].status == "delivered"
    assert memory.sent_messages == (response,)


async def test_channel_dispatcher_returns_accepted_without_sending() -> None:
    memory = MemoryChannel()
    handler = StubHandler(ChannelHandlerResult(status="accepted"))
    dispatcher = ChannelDispatcher(handler, StubIdentityResolver(), memory, memory)

    result = await dispatcher.dispatch(_incoming())

    assert result.status == "accepted"
    assert result.receipts == ()
    assert memory.sent_messages == ()


async def test_channel_dispatcher_deduplicates_before_application_calls() -> None:
    memory = MemoryChannel()
    resolver = StubIdentityResolver()
    handler = StubHandler(ChannelHandlerResult())
    dispatcher = ChannelDispatcher(handler, resolver, memory, memory)

    first = await dispatcher.dispatch(_incoming())
    duplicate = await dispatcher.dispatch(_incoming())

    assert first.status == "completed"
    assert duplicate.status == "duplicate"
    assert resolver.calls == 1
    assert handler.calls == 1


@pytest.mark.parametrize("failure", ["identity", "handler"])
async def test_channel_dispatcher_releases_pre_dispatch_failures(failure: str) -> None:
    memory = MemoryChannel()
    resolver = StubIdentityResolver(fail=failure == "identity")
    handler = StubHandler(ChannelHandlerResult(), fail=failure == "handler")
    dispatcher = ChannelDispatcher(handler, resolver, memory, memory)

    with pytest.raises(RuntimeError):
        await dispatcher.dispatch(_incoming())

    resolver.fail = False
    handler.fail = False
    result = await dispatcher.dispatch(_incoming())
    assert result.status == "completed"


async def test_channel_dispatcher_keeps_claim_after_outbound_failure() -> None:
    memory = MemoryChannel()
    handler = StubHandler(ChannelHandlerResult(responses=(_response(),)))
    dispatcher = ChannelDispatcher(
        handler,
        StubIdentityResolver(),
        memory,
        FailingSender(),
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await dispatcher.dispatch(_incoming())

    assert (await dispatcher.dispatch(_incoming())).status == "duplicate"
    assert handler.calls == 1


def test_channel_dispatcher_requires_positive_event_ttl() -> None:
    memory = MemoryChannel()

    with pytest.raises(ValueError, match="greater than zero"):
        ChannelDispatcher(
            StubHandler(ChannelHandlerResult()),
            StubIdentityResolver(),
            memory,
            memory,
            event_ttl_seconds=0,
        )
