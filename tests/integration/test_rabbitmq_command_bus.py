from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest

from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus
from arclith.application.command_bus import CommandDispatcher
from arclith.domain.ports.inbound.command_bus import CommandHandler
from arclith.infrastructure.config import RabbitMQCommandBusSettings

pytestmark = pytest.mark.skipif(
    not os.getenv("ARCLITH_RABBITMQ_URL"),
    reason="ARCLITH_RABBITMQ_URL non configure",
)


class RecordingHandler(CommandHandler):
    command_type = "todo.create"

    def __init__(self) -> None:
        self.payloads: list[Mapping[str, Any]] = []

    async def handle(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> None:
        self.payloads.append(payload)


async def test_rabbitmq_command_bus_smoke(logger) -> None:
    pytest.importorskip("aio_pika")
    suffix = uuid4().hex
    settings = RabbitMQCommandBusSettings(
        url=os.environ["ARCLITH_RABBITMQ_URL"],
        exchange=f"arclith.tests.commands.{suffix}",
        queue=f"arclith.tests.commands.{suffix}",
        routing_key=f"commands.{suffix}",
        dead_letter_exchange=f"arclith.tests.commands.{suffix}.dlx",
        dead_letter_routing_key=f"commands.{suffix}.dead",
        durable=False,
    )
    handler = RecordingHandler()
    dispatcher = CommandDispatcher([handler])
    bus = RabbitMQCommandBus(settings, logger)

    await bus.connect()
    try:
        await bus.publish("todo.create", {"title": "smoke"})
        assert bus._queue is not None
        message = await bus._queue.get(timeout=5)
        await bus.handle_message(message, dispatcher)
    finally:
        if bus._queue is not None:
            await bus._queue.delete(if_unused=False, if_empty=False)
        if bus._exchange is not None:
            await bus._exchange.delete(if_unused=False)
        await bus.close()

    assert handler.payloads == [{"title": "smoke"}]
