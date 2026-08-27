from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import uuid4

from arclith.adapters.outbound.opentelemetry.correlation import current_trace_metadata
from arclith.application.command_bus import (
    CommandDispatcher,
    CommandEnvelope,
    InvalidCommandMessageError,
    decode_command_message,
    encode_command_message,
)
from arclith.domain.ports.outbound.command_bus import CommandPublisher
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.observability import TracePort
from arclith.infrastructure.config import RabbitMQCommandBusSettings

type AioPikaModule = Any
type Connector = Callable[[str], Awaitable[Any]]


class RabbitMQCommandBus(CommandPublisher):
    """RabbitMQ command-bus adapter backed by aio-pika robust connections."""

    def __init__(
        self,
        settings: RabbitMQCommandBusSettings,
        logger: Logger,
        *,
        tracer: TracePort | None = None,
        connector: Connector | None = None,
        aio_pika_module: AioPikaModule | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        if tracer is None:
            from arclith.adapters.outbound.noop.observability import NoOpTraceAdapter

            tracer = NoOpTraceAdapter()
        self._tracer = tracer
        self._connector = connector
        self._aio_pika = aio_pika_module
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._exchange: Any | None = None
        self._queue: Any | None = None

    async def connect(self) -> None:
        if self._connection is not None:
            return

        aio_pika = self._load_aio_pika()
        connector = self._connector or aio_pika.connect_robust
        self._connection = await connector(self._settings.url)
        self._channel = await self._connection.channel(
            publisher_confirms=self._settings.publisher_confirms,
        )
        await self._channel.set_qos(prefetch_count=self._settings.prefetch)
        self._exchange = await self._channel.declare_exchange(
            self._settings.exchange,
            self._exchange_type(aio_pika),
            durable=self._settings.durable,
        )
        if self._settings.retry_enabled and self._settings.dead_letter_exchange:
            await self._channel.declare_exchange(
                self._settings.dead_letter_exchange,
                self._exchange_type(aio_pika),
                durable=self._settings.durable,
            )
        self._queue = await self._channel.declare_queue(
            self._settings.queue,
            durable=self._settings.durable,
            arguments=self._queue_arguments(),
        )
        await self._queue.bind(self._exchange, routing_key=self._settings.routing_key)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None
        self._queue = None

    async def publish(
        self,
        command_type: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        routing_key: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        await self.connect()
        if self._exchange is None:
            raise RuntimeError("RabbitMQ exchange non initialise")

        aio_pika = self._load_aio_pika()
        with self._tracer.span(
            "rabbitmq.publish",
            kind="tool",
            metadata={
                "messaging.system": "rabbitmq",
                "messaging.destination.name": self._settings.exchange,
                "messaging.operation.name": "publish",
                "messaging.command.type": command_type,
            },
        ) as span:
            message_headers = self._message_headers(
                command_type,
                headers=headers,
                correlation_id=correlation_id,
            )
            message = aio_pika.Message(
                body=encode_command_message(
                    CommandEnvelope(
                        command_type=command_type,
                        payload=dict(payload),
                        headers=message_headers,
                    )
                ),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers=message_headers,
                correlation_id=message_headers["correlation_id"],
            )
            await self._exchange.publish(
                message,
                routing_key=routing_key or self._settings.routing_key,
            )
            span.set_outputs({"status": "published"})

    async def handle_message(self, message: Any, dispatcher: CommandDispatcher) -> None:
        headers = self._headers_from_message(message)
        fallback_command_type = headers.get(
            "command_type",
            getattr(message, "routing_key", self._settings.routing_key),
        )
        try:
            envelope = decode_command_message(
                message.body,
                headers=headers,
                fallback_command_type=fallback_command_type,
            )
        except InvalidCommandMessageError as exc:
            await message.nack(requeue=False)
            self._logger.error(
                "RabbitMQ command payload rejected",
                command_type=fallback_command_type,
                correlation_id=headers.get("correlation_id"),
                retry_requeue=False,
                error=str(exc),
            )
            return

        with self._tracer.context(
            parent=headers,
            metadata={"correlation.id": headers.get("correlation_id", "")},
        ):
            with self._tracer.span(
                "rabbitmq.process",
                kind="chain",
                metadata={
                    "messaging.system": "rabbitmq",
                    "messaging.destination.name": self._settings.queue,
                    "messaging.operation.name": "process",
                    "messaging.command.type": fallback_command_type,
                },
            ) as span:
                try:
                    await dispatcher.dispatch(envelope)
                except Exception as exc:
                    await message.nack(
                        requeue=(
                            self._settings.retry_enabled
                            and self._settings.retry_requeue
                        )
                    )
                    self._logger.error(
                        "RabbitMQ command rejected",
                        command_type=fallback_command_type,
                        correlation_id=headers.get("correlation_id"),
                        retry_requeue=self._settings.retry_requeue,
                        error=str(exc),
                    )
                    span.set_metadata({"error.type": type(exc).__name__})
                    span.set_outputs({"status": "rejected"})
                    return

                await message.ack()
                span.set_outputs({"status": "acknowledged"})
                self._logger.info(
                    "RabbitMQ command acknowledged",
                    command_type=fallback_command_type,
                    correlation_id=headers.get("correlation_id"),
                )

    async def run(self, dispatcher: CommandDispatcher) -> None:
        await self.connect()
        if self._queue is None:
            raise RuntimeError("RabbitMQ queue non initialisee")

        semaphore = asyncio.Semaphore(self._settings.concurrency)
        tasks: set[asyncio.Task[None]] = set()

        async with self._queue.iterator(
            consumer_tag=self._settings.consumer_name
        ) as queue_iter:
            async for message in queue_iter:
                await semaphore.acquire()
                task = asyncio.create_task(
                    self._handle_with_semaphore(message, dispatcher, semaphore)
                )
                tasks.add(task)
                task.add_done_callback(tasks.discard)

        if tasks:
            await asyncio.gather(*tasks)

    async def _handle_with_semaphore(
        self,
        message: Any,
        dispatcher: CommandDispatcher,
        semaphore: asyncio.Semaphore,
    ) -> None:
        try:
            await self.handle_message(message, dispatcher)
        finally:
            semaphore.release()

    def _message_headers(
        self,
        command_type: str,
        *,
        headers: Mapping[str, str] | None,
        correlation_id: str | None,
    ) -> dict[str, str]:
        normalized = {str(key): str(value) for key, value in (headers or {}).items()}
        normalized["command_type"] = command_type
        normalized.setdefault("correlation_id", correlation_id or str(uuid4()))
        traceparent = self._current_traceparent()
        if traceparent:
            normalized.setdefault("traceparent", traceparent)
        self._tracer.inject(normalized)
        return normalized

    @staticmethod
    def _headers_from_message(message: Any) -> dict[str, str]:
        headers = getattr(message, "headers", None) or {}
        normalized = {str(key): str(value) for key, value in headers.items()}
        correlation_id = getattr(message, "correlation_id", None)
        if correlation_id:
            normalized.setdefault("correlation_id", str(correlation_id))
        return normalized

    def _queue_arguments(self) -> dict[str, str] | None:
        if not self._settings.retry_enabled or not self._settings.dead_letter_exchange:
            return None
        return {
            "x-dead-letter-exchange": self._settings.dead_letter_exchange,
            "x-dead-letter-routing-key": self._settings.dead_letter_routing_key,
        }

    def _exchange_type(self, aio_pika: AioPikaModule) -> Any:
        exchange_type = self._settings.exchange_type.upper()
        return getattr(aio_pika.ExchangeType, exchange_type)

    @staticmethod
    def _current_traceparent() -> str:
        metadata = current_trace_metadata()
        if not metadata:
            return ""
        trace_flags = "01" if metadata.get("trace_sampled") else "00"
        return f"00-{metadata['trace_id']}-{metadata['span_id']}-{trace_flags}"

    def _load_aio_pika(self) -> AioPikaModule:
        if self._aio_pika is not None:
            return self._aio_pika
        try:
            import aio_pika
        except ImportError as exc:
            raise ModuleNotFoundError(
                "aio-pika est requis pour RabbitMQ. Installer arclith[rabbitmq] ou arclith[all]."
            ) from exc
        self._aio_pika = aio_pika
        return aio_pika
