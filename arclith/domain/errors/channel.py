from __future__ import annotations


class ChannelError(Exception):
    """Base error exposed by channel adapters and application services."""


class InvalidChannelSignature(ChannelError):
    """Raised when a provider signature is missing, stale, or invalid."""


class ChannelUnauthorized(ChannelError):
    """Raised when provider or application authorization rejects a message."""


class UnsupportedChannelEvent(ChannelError):
    """Raised when an adapter cannot normalize a provider event."""


class ChannelIdentityNotResolved(ChannelError):
    """Raised when an external identity has no explicit application mapping."""


class ChannelRateLimited(ChannelError):
    """Raised when a provider rate-limits an outbound delivery."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ChannelDeliveryFailed(ChannelError):
    """Raised when a provider rejects or fails an outbound delivery."""


class ChannelUnavailable(ChannelError):
    """Raised when a provider or transport is unavailable."""
