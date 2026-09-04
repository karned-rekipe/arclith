from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime, timezone

from arclith.domain.errors.channel import ChannelIdentityNotResolved
from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelIdentity,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)

IdentityKey = tuple[str, str, str | None, str | None]


def _identity_key(identity: ChannelIdentity) -> IdentityKey:
    return (
        identity.provider,
        identity.external_user_id,
        identity.external_tenant_id,
        identity.external_workspace_id,
    )


class MemoryChannelIdentityResolver(ChannelIdentityResolver):
    """Explicit in-memory identity mapping for deterministic tests and POCs."""

    def __init__(self) -> None:
        self._mappings: dict[IdentityKey, ResolvedChannelIdentity] = {}

    def register(
        self,
        identity: ChannelIdentity,
        resolved: ResolvedChannelIdentity,
    ) -> None:
        self._mappings[_identity_key(identity)] = resolved

    async def resolve(self, identity: ChannelIdentity) -> ResolvedChannelIdentity:
        try:
            return self._mappings[_identity_key(identity)]
        except KeyError:
            raise ChannelIdentityNotResolved(
                "No application mapping for external channel identity"
            ) from None


class MemoryChannel(ChannelEventStore, ChannelSender):
    """Dependency-free sender and atomic event store for tests and local POCs."""

    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self._claims: dict[tuple[str, str], float] = {}
        self._sent_messages: list[ChannelOutgoingMessage] = []
        self._receipts: list[ChannelDeliveryReceipt] = []
        self._lock = asyncio.Lock()

    @property
    def sent_messages(self) -> tuple[ChannelOutgoingMessage, ...]:
        return tuple(self._sent_messages)

    @property
    def receipts(self) -> tuple[ChannelDeliveryReceipt, ...]:
        return tuple(self._receipts)

    async def claim(
        self,
        provider: str,
        event_id: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("channel event ttl_seconds must be greater than zero")
        key = (provider, event_id)
        async with self._lock:
            now = self._monotonic_clock()
            self._discard_expired_claims(now)
            if key in self._claims:
                return False
            self._claims[key] = now + ttl_seconds
            return True

    async def release(self, provider: str, event_id: str) -> None:
        async with self._lock:
            self._claims.pop((provider, event_id), None)

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        async with self._lock:
            receipt = ChannelDeliveryReceipt(
                message_id=message.message_id,
                provider_message_id=f"memory-{len(self._receipts) + 1:04d}",
                status="delivered",
                timestamp=self._utc_clock(),
            )
            self._sent_messages.append(message)
            self._receipts.append(receipt)
            return receipt

    def _discard_expired_claims(self, now: float) -> None:
        expired = [key for key, expires_at in self._claims.items() if expires_at <= now]
        for key in expired:
            del self._claims[key]
