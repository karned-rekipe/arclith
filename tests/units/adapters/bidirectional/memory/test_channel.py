from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.domain.errors.channel import ChannelIdentityNotResolved
from arclith.domain.models.channel import (
    ChannelIdentity,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        provider="slack",
        external_user_id="U123",
        external_workspace_id="T123",
    )


async def test_memory_identity_resolver_requires_explicit_mapping() -> None:
    resolver = MemoryChannelIdentityResolver()

    with pytest.raises(ChannelIdentityNotResolved, match="No application mapping"):
        await resolver.resolve(_identity())

    expected = ResolvedChannelIdentity(user_id="user-1", tenant_id="tenant-a")
    resolver.register(_identity(), expected)

    assert await resolver.resolve(_identity()) == expected


async def test_memory_channel_claim_is_atomic_for_concurrent_retries() -> None:
    channel = MemoryChannel()

    results = await asyncio.gather(
        *(channel.claim("slack", "Ev123", ttl_seconds=60) for _ in range(20))
    )

    assert results.count(True) == 1
    assert results.count(False) == 19


async def test_memory_channel_releases_and_expires_claims() -> None:
    now = [10.0]
    channel = MemoryChannel(monotonic_clock=lambda: now[0])

    assert await channel.claim("slack", "Ev123", ttl_seconds=5) is True
    assert await channel.claim("slack", "Ev123", ttl_seconds=5) is False

    await channel.release("slack", "Ev123")
    assert await channel.claim("slack", "Ev123", ttl_seconds=5) is True

    now[0] = 15.0
    assert await channel.claim("slack", "Ev123", ttl_seconds=5) is True


async def test_memory_channel_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        await MemoryChannel().claim("slack", "Ev123", ttl_seconds=0)


async def test_memory_channel_records_deterministic_deliveries() -> None:
    fixed_time = datetime(2026, 9, 4, 10, tzinfo=timezone.utc)
    channel = MemoryChannel(utc_clock=lambda: fixed_time)
    first = ChannelOutgoingMessage(
        message_id="msg-1",
        channel="slack",
        conversation_id="C123",
        text="first",
    )
    second = first.model_copy(update={"message_id": "msg-2", "text": "second"})

    first_receipt = await channel.send(first)
    second_receipt = await channel.send(second)
    await channel.close()

    assert first_receipt.provider_message_id == "memory-0001"
    assert second_receipt.provider_message_id == "memory-0002"
    assert first_receipt.timestamp == fixed_time
    assert channel.sent_messages == (first, second)
    assert channel.receipts == (first_receipt, second_receipt)
