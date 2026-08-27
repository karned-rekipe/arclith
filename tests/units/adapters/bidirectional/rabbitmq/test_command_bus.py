from __future__ import annotations

import builtins
import json
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus
from arclith.application.command_bus import CommandDispatcher
from arclith.domain.ports.inbound.command_bus import CommandHandler
from arclith.domain.ports.outbound.observability import MetricPort, TracePort, TraceSpan
from arclith.infrastructure.config import RabbitMQCommandBusSettings


class FakePublishedMessage:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.body: bytes = kwargs["body"]
        self.headers: dict[str, str] = kwargs["headers"]
        self.correlation_id: str = kwargs["correlation_id"]


class FakeExchange:
    def __init__(self, name: str, exchange_type: str, durable: bool) -> None:
        self.name = name
        self.exchange_type = exchange_type
        self.durable = durable
        self.published: list[tuple[FakePublishedMessage, str]] = []

    async def publish(self, message: FakePublishedMessage, routing_key: str) -> None:
        self.published.append((message, routing_key))


class FakeQueue:
    def __init__(
        self, name: str, durable: bool, arguments: dict[str, str] | None
    ) -> None:
        self.name = name
        self.durable = durable
        self.arguments = arguments
        self.bindings: list[tuple[FakeExchange, str]] = []
        self.messages: list[FakeIncomingMessage] = []
        self.iterator_kwargs: dict[str, Any] | None = None

    async def bind(self, exchange: FakeExchange, routing_key: str) -> None:
        self.bindings.append((exchange, routing_key))

    def iterator(self, **kwargs: Any) -> "FakeQueueIterator":
        self.iterator_kwargs = kwargs
        return FakeQueueIterator(self.messages)


class FakeQueueIterator:
    def __init__(self, messages: list["FakeIncomingMessage"]) -> None:
        self._messages = messages
        self._index = 0

    async def __aenter__(self) -> "FakeQueueIterator":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def __aiter__(self) -> "FakeQueueIterator":
        return self

    async def __anext__(self) -> "FakeIncomingMessage":
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        message = self._messages[self._index]
        self._index += 1
        return message


class FakeChannel:
    def __init__(self, *, publisher_confirms: bool) -> None:
        self.publisher_confirms = publisher_confirms
        self.prefetch_count: int | None = None
        self.exchanges: dict[str, FakeExchange] = {}
        self.queue: FakeQueue | None = None

    async def set_qos(self, *, prefetch_count: int) -> None:
        self.prefetch_count = prefetch_count

    async def declare_exchange(
        self, name: str, exchange_type: str, *, durable: bool
    ) -> FakeExchange:
        exchange = FakeExchange(name, exchange_type, durable)
        self.exchanges[name] = exchange
        return exchange

    async def declare_queue(
        self,
        name: str,
        *,
        durable: bool,
        arguments: dict[str, str] | None,
    ) -> FakeQueue:
        self.queue = FakeQueue(name, durable, arguments)
        return self.queue


class FakeConnection:
    def __init__(self) -> None:
        self.channel_instance: FakeChannel | None = None
        self.closed = False

    async def channel(self, *, publisher_confirms: bool) -> FakeChannel:
        self.channel_instance = FakeChannel(publisher_confirms=publisher_confirms)
        return self.channel_instance

    async def close(self) -> None:
        self.closed = True


class FakeIncomingMessage:
    def __init__(
        self,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        routing_key: str = "commands",
        correlation_id: str | None = None,
    ) -> None:
        self.body = body
        self.headers = headers
        self.routing_key = routing_key
        self.correlation_id = correlation_id
        self.acked = False
        self.nacked: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool) -> None:
        self.nacked = requeue


class RecordingHandler(CommandHandler):
    command_type = "todo.create"

    def __init__(self) -> None:
        self.calls: list[tuple[Mapping[str, Any], Mapping[str, str]]] = []

    async def handle(
        self, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> None:
        self.calls.append((payload, headers))


class FailingHandler(CommandHandler):
    command_type = "todo.create"

    async def handle(
        self, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> None:
        raise RuntimeError("boom")


FakeAioPika = SimpleNamespace(
    DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
    ExchangeType=SimpleNamespace(DIRECT="direct", TOPIC="topic"),
    Message=FakePublishedMessage,
)


class RecordingTraceSpan(TraceSpan):
    def set_outputs(self, outputs: object | None) -> None:
        return None

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        return None


class RecordingTracer(TracePort):
    def __init__(self) -> None:
        self.span_names: list[str] = []
        self.span_metadata: list[dict[str, object]] = []
        self.parents: list[Mapping[str, str] | None] = []
        self.events: list[str] = []

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        self.span_names.append(name)
        self.span_metadata.append(dict(metadata or {}))
        self.events.append(f"span:{name}")
        yield RecordingTraceSpan()

    @contextmanager
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        self.parents.append(parent)
        yield

    def inject(self, headers: MutableMapping[str, str]) -> None:
        self.events.append("inject")
        headers["langsmith-trace"] = "trace-value"
        headers["traceparent"] = f"00-{'a' * 32}-{'b' * 16}-01"

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None


class RecordingMetrics(MetricPort):
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, object]]] = []
        self.histograms: list[tuple[str, dict[str, object]]] = []

    def add_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "1",
    ) -> None:
        self.counters.append((name, dict(attributes or {})))

    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "ms",
    ) -> None:
        self.histograms.append((name, dict(attributes or {})))


async def test_rabbitmq_command_bus_publish_configures_reliable_channel(logger) -> None:
    connection = FakeConnection()

    async def connector(url: str) -> FakeConnection:
        assert url == "amqp://broker/"
        return connection

    settings = RabbitMQCommandBusSettings(
        url="amqp://broker/",
        exchange="commands.exchange",
        queue="commands.queue",
        routing_key="commands.route",
        prefetch=7,
    )
    bus = RabbitMQCommandBus(
        settings,
        logger,
        connector=connector,
        aio_pika_module=FakeAioPika,
    )

    await bus.publish("todo.create", {"title": "write docs"}, correlation_id="corr-1")

    channel = connection.channel_instance
    assert channel is not None
    assert channel.publisher_confirms is True
    assert channel.prefetch_count == 7
    assert channel.queue is not None
    assert channel.queue.arguments == {
        "x-dead-letter-exchange": "arclith.commands.dlx",
        "x-dead-letter-routing-key": "commands.dead",
    }
    assert channel.queue.bindings[0][1] == "commands.route"
    message, routing_key = channel.exchanges["commands.exchange"].published[0]
    assert routing_key == "commands.route"
    assert message.headers["command_type"] == "todo.create"
    assert message.headers["correlation_id"] == "corr-1"
    assert message.correlation_id == "corr-1"
    assert message.kwargs["delivery_mode"] == "persistent"
    assert json.loads(message.body) == {
        "type": "todo.create",
        "payload": {"title": "write docs"},
    }
    await bus.close()
    assert connection.closed is True


async def test_rabbitmq_command_bus_connect_can_disable_retry_dlx(logger) -> None:
    connection = FakeConnection()

    async def connector(url: str) -> FakeConnection:
        assert url == "amqp://broker/"
        return connection

    settings = RabbitMQCommandBusSettings(
        url="amqp://broker/",
        exchange_type="direct",
        retry_enabled=False,
    )
    bus = RabbitMQCommandBus(
        settings,
        logger,
        connector=connector,
        aio_pika_module=FakeAioPika,
    )

    await bus.connect()

    channel = connection.channel_instance
    assert channel is not None
    assert channel.exchanges["arclith.commands"].exchange_type == "direct"
    assert "arclith.commands.dlx" not in channel.exchanges
    assert channel.queue is not None
    assert channel.queue.arguments is None


async def test_rabbitmq_command_bus_publish_adds_current_traceparent(
    logger,
) -> None:
    connection = FakeConnection()

    async def connector(url: str) -> FakeConnection:
        assert url == "amqp://broker/"
        return connection

    settings = RabbitMQCommandBusSettings(url="amqp://broker/")
    tracer = RecordingTracer()
    bus = RabbitMQCommandBus(
        settings,
        logger,
        tracer=tracer,
        connector=connector,
        aio_pika_module=FakeAioPika,
    )

    await bus.publish("todo.create", {"title": "write docs"})

    channel = connection.channel_instance
    assert channel is not None
    message, _routing_key = channel.exchanges["arclith.commands"].published[0]
    assert message.headers["traceparent"] == f"00-{'a' * 32}-{'b' * 16}-01"


async def test_rabbitmq_command_bus_propagates_langsmith_context(logger) -> None:
    connection = FakeConnection()

    async def connector(url: str) -> FakeConnection:
        return connection

    tracer = RecordingTracer()
    bus = RabbitMQCommandBus(
        RabbitMQCommandBusSettings(url="amqp://broker/"),
        logger,
        tracer=tracer,
        connector=connector,
        aio_pika_module=FakeAioPika,
    )

    await bus.publish("todo.create", {"title": "write docs"})

    channel = connection.channel_instance
    assert channel is not None
    message, _routing_key = channel.exchanges["arclith.commands"].published[0]
    assert message.headers["langsmith-trace"] == "trace-value"
    assert tracer.span_names == ["rabbitmq.publish"]
    assert tracer.events == ["span:rabbitmq.publish", "inject"]


async def test_rabbitmq_command_bus_extracts_context_for_handler(logger) -> None:
    tracer = RecordingTracer()
    handler = RecordingHandler()
    dispatcher = CommandDispatcher([handler])
    message = FakeIncomingMessage(
        b'{"payload": {"title": "write docs"}}',
        headers={
            "command_type": "todo.create",
            "langsmith-trace": "trace-value",
            "baggage": "safe=yes",
        },
    )
    bus = RabbitMQCommandBus(
        RabbitMQCommandBusSettings(),
        logger,
        tracer=tracer,
        aio_pika_module=FakeAioPika,
    )

    await bus.handle_message(message, dispatcher)

    assert tracer.parents == [
        {
            "command_type": "todo.create",
            "langsmith-trace": "trace-value",
            "baggage": "safe=yes",
        }
    ]
    assert tracer.span_names == ["rabbitmq.process"]
    assert message.acked is True


async def test_rabbitmq_command_bus_acks_after_dispatch_success(logger) -> None:
    handler = RecordingHandler()
    dispatcher = CommandDispatcher([handler])
    message = FakeIncomingMessage(
        b'{"payload": {"title": "write docs"}}',
        headers={"command_type": "todo.create"},
        correlation_id="corr-1",
    )
    bus = RabbitMQCommandBus(
        RabbitMQCommandBusSettings(), logger, aio_pika_module=FakeAioPika
    )

    await bus.handle_message(message, dispatcher)

    assert message.acked is True
    assert message.nacked is None
    assert handler.calls == [
        (
            {"title": "write docs"},
            {"command_type": "todo.create", "correlation_id": "corr-1"},
        )
    ]


async def test_rabbitmq_command_bus_nacks_to_dlx_after_dispatch_error(logger) -> None:
    dispatcher = CommandDispatcher([FailingHandler()])
    message = FakeIncomingMessage(
        b'{"payload": {"title": "write docs"}}',
        headers={"command_type": "todo.create"},
        correlation_id="corr-1",
    )
    bus = RabbitMQCommandBus(
        RabbitMQCommandBusSettings(), logger, aio_pika_module=FakeAioPika
    )

    await bus.handle_message(message, dispatcher)

    assert message.acked is False
    assert message.nacked is False


async def test_rabbitmq_command_bus_records_bounded_retry_and_redelivery_metrics(
    logger,
) -> None:
    dispatcher = CommandDispatcher([FailingHandler()])
    message = FakeIncomingMessage(
        b'{"payload": {"title": "write docs"}}',
        headers={"command_type": "todo.create"},
    )
    message.redelivered = True
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    bus = RabbitMQCommandBus(
        RabbitMQCommandBusSettings(retry_requeue=True),
        logger,
        tracer=tracer,
        metrics=metrics,
        aio_pika_module=FakeAioPika,
    )

    await bus.handle_message(message, dispatcher)

    assert message.nacked is True
    assert tracer.span_metadata[0]["messaging.message.redelivery_count"] == 1
    assert [name for name, _ in metrics.counters] == [
        "arclith.messaging.operations",
        "arclith.messaging.retries",
        "arclith.messaging.rejected",
    ]
    assert metrics.histograms[0][0] == "arclith.messaging.duration"
    assert "payload" not in repr(metrics.counters)


async def test_rabbitmq_command_bus_invalid_json_never_requeues(logger) -> None:
    dispatcher = CommandDispatcher([RecordingHandler()])
    message = FakeIncomingMessage(
        b"{invalid",
        headers={"command_type": "todo.create"},
        correlation_id="corr-1",
    )
    settings = RabbitMQCommandBusSettings(retry_requeue=True)
    bus = RabbitMQCommandBus(settings, logger, aio_pika_module=FakeAioPika)

    await bus.handle_message(message, dispatcher)

    assert message.acked is False
    assert message.nacked is False


async def test_rabbitmq_command_bus_run_uses_named_consumer_and_dispatches(
    logger,
) -> None:
    connection = FakeConnection()

    async def connector(url: str) -> FakeConnection:
        assert url == "amqp://broker/"
        return connection

    settings = RabbitMQCommandBusSettings(
        url="amqp://broker/",
        consumer_name="worker-1",
        concurrency=2,
    )
    bus = RabbitMQCommandBus(
        settings,
        logger,
        connector=connector,
        aio_pika_module=FakeAioPika,
    )
    await bus.connect()
    channel = connection.channel_instance
    assert channel is not None
    assert channel.queue is not None
    message = FakeIncomingMessage(
        b'{"payload": {"title": "write docs"}}',
        headers={"command_type": "todo.create"},
    )
    channel.queue.messages.append(message)
    handler = RecordingHandler()

    await bus.run(CommandDispatcher([handler]))

    assert channel.queue.iterator_kwargs == {"consumer_tag": "worker-1"}
    assert message.acked is True
    assert handler.calls == [({"title": "write docs"}, {"command_type": "todo.create"})]


def test_rabbitmq_command_bus_missing_extra_has_actionable_error(
    logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: dict | None = None,
        locals: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "aio_pika":
            raise ModuleNotFoundError("No module named 'aio_pika'", name="aio_pika")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    bus = RabbitMQCommandBus(RabbitMQCommandBusSettings(), logger)

    with pytest.raises(ModuleNotFoundError, match=r"arclith\[rabbitmq\]"):
        bus._load_aio_pika()
