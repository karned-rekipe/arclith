from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from arclith.domain.ports.inbound.command_bus import CommandHandler


class CommandBusError(Exception):
    """Base error for command-bus dispatch and serialization failures."""


class UnknownCommandError(CommandBusError):
    """Raised when no registered handler matches a command type."""


class InvalidCommandMessageError(CommandBusError):
    """Raised when a broker message cannot be decoded into a command envelope."""


@dataclass(frozen=True)
class CommandEnvelope:
    command_type: str
    payload: Mapping[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command_type.strip():
            raise ValueError("command_type est requis")


class CommandDispatcher:
    """Dispatch command envelopes to registered application handlers."""

    def __init__(self, handlers: Iterable[CommandHandler] = ()) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        for handler in handlers:
            self.register(handler)

    @property
    def command_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def register(self, handler: CommandHandler) -> None:
        command_type = handler.command_type.strip()
        if not command_type:
            raise ValueError("handler.command_type est requis")
        if command_type in self._handlers:
            raise ValueError(f"handler deja enregistre pour command_type={command_type}")
        self._handlers[command_type] = handler

    async def dispatch(self, envelope: CommandEnvelope) -> None:
        handler = self._handlers.get(envelope.command_type)
        if handler is None:
            raise UnknownCommandError(f"Aucun handler pour command_type={envelope.command_type}")
        await handler.handle(envelope.payload, envelope.headers)


def encode_command_message(envelope: CommandEnvelope) -> bytes:
    body = {
        "type": envelope.command_type,
        "payload": dict(envelope.payload),
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_command_message(
    body: bytes,
    *,
    headers: Mapping[str, str],
    fallback_command_type: str,
) -> CommandEnvelope:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCommandMessageError("message command-bus JSON invalide") from exc

    if isinstance(decoded, dict) and "payload" in decoded:
        payload = decoded["payload"]
        command_type = str(decoded.get("type") or decoded.get("command_type") or fallback_command_type)
    else:
        payload = decoded
        command_type = headers.get("command_type", fallback_command_type)

    if not isinstance(payload, dict):
        raise InvalidCommandMessageError("message command-bus payload doit etre un objet JSON")

    return CommandEnvelope(command_type=command_type, payload=payload, headers=dict(headers))
