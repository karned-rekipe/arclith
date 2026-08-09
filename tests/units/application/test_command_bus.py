from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from arclith.application.command_bus import (
    CommandDispatcher,
    CommandEnvelope,
    InvalidCommandMessageError,
    UnknownCommandError,
    decode_command_message,
    encode_command_message,
)
from arclith.domain.ports.inbound.command_bus import CommandHandler


class RecordingHandler(CommandHandler):
    command_type = "todo.create"

    def __init__(self) -> None:
        self.calls: list[tuple[Mapping[str, Any], Mapping[str, str]]] = []

    async def handle(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> None:
        self.calls.append((payload, headers))


async def test_command_dispatcher_invokes_matching_handler() -> None:
    handler = RecordingHandler()
    dispatcher = CommandDispatcher([handler])

    await dispatcher.dispatch(
        CommandEnvelope(
            command_type="todo.create",
            payload={"title": "write docs"},
            headers={"correlation_id": "corr-1"},
        )
    )

    assert dispatcher.command_types == ("todo.create",)
    assert handler.calls == [({"title": "write docs"}, {"correlation_id": "corr-1"})]


async def test_command_dispatcher_rejects_unknown_command() -> None:
    dispatcher = CommandDispatcher()

    with pytest.raises(UnknownCommandError, match="todo.create"):
        await dispatcher.dispatch(CommandEnvelope(command_type="todo.create", payload={}))


def test_command_dispatcher_rejects_duplicate_handler() -> None:
    dispatcher = CommandDispatcher([RecordingHandler()])

    with pytest.raises(ValueError, match="deja enregistre"):
        dispatcher.register(RecordingHandler())


def test_command_message_round_trip() -> None:
    envelope = CommandEnvelope(
        command_type="todo.create",
        payload={"title": "write docs"},
        headers={"correlation_id": "corr-1"},
    )

    decoded = decode_command_message(
        encode_command_message(envelope),
        headers=envelope.headers,
        fallback_command_type="fallback",
    )

    assert decoded == envelope


def test_command_message_can_use_header_command_type_for_raw_payload() -> None:
    decoded = decode_command_message(
        b'{"title": "write docs"}',
        headers={"command_type": "todo.create"},
        fallback_command_type="fallback",
    )

    assert decoded.command_type == "todo.create"
    assert decoded.payload == {"title": "write docs"}


def test_command_message_rejects_invalid_json_payload() -> None:
    with pytest.raises(InvalidCommandMessageError, match="JSON invalide"):
        decode_command_message(b"{", headers={}, fallback_command_type="todo.create")

    with pytest.raises(InvalidCommandMessageError, match="objet JSON"):
        decode_command_message(b'{"payload": []}', headers={}, fallback_command_type="todo.create")
