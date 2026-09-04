from __future__ import annotations

from abc import ABC, abstractmethod

from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelIdentity,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)


class ChannelIdentityResolver(ABC):
    """Map untrusted provider identities to application user and tenant IDs."""

    @abstractmethod
    async def resolve(self, identity: ChannelIdentity) -> ResolvedChannelIdentity:
        raise NotImplementedError


class ChannelEventStore(ABC):
    """Atomically reserve provider events so concurrent retries run only once."""

    @abstractmethod
    async def claim(
        self,
        provider: str,
        event_id: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        """Return true only for the caller that atomically reserves the event."""
        raise NotImplementedError

    @abstractmethod
    async def release(self, provider: str, event_id: str) -> None:
        """Release a failed pre-dispatch reservation so the provider can retry."""
        raise NotImplementedError


class ChannelSender(ABC):
    """Outbound port for sending provider-neutral channel responses."""

    async def close(self) -> None:
        """Release owned provider resources when the adapter has any."""
        return None

    @abstractmethod
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        raise NotImplementedError
