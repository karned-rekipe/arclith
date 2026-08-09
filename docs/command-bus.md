# Command Bus RabbitMQ

## Objectif

`command-bus/rabbitmq` permet d'exposer les mêmes use cases qu'une API ou un MCP via un worker
RabbitMQ. Le chemin reste hexagonal:

```text
RabbitMQ message
  -> CommandEnvelope
  -> CommandDispatcher
  -> CommandHandler projet
  -> DTO / command applicative
  -> use case ou port inbound
```

Le framework ne fournit aucune logique métier. Le handler appartient au projet consommateur et
valide le payload avant d'appeler le cas d'usage.

## Configuration

```bash
uv add "arclith[rabbitmq]"

arclith-cli add-adapter \
  --capability command-bus \
  --adapter rabbitmq \
  --param url=amqp://guest:guest@127.0.0.1:5672/ \
  --param exchange=arclith.commands \
  --param exchange_type=topic \
  --param queue=arclith.commands \
  --param routing_key=commands \
  --param prefetch=10 \
  --param consumer_name=arclith-command-worker \
  --param concurrency=1 \
  --yes
```

```yaml
# config/command_bus.yaml
enabled:
  - rabbitmq
rabbitmq:
  url: "amqp://guest:guest@127.0.0.1:5672/"
  exchange: "arclith.commands"
  exchange_type: "topic"
  queue: "arclith.commands"
  routing_key: "commands"
  prefetch: 10
  consumer_name: "arclith-command-worker"
  concurrency: 1
  publisher_confirms: true
  durable: true
  retry_enabled: true
  retry_requeue: false
  dead_letter_exchange: "arclith.commands.dlx"
  dead_letter_routing_key: "commands.dead"
```

`prefetch` et `concurrency` sont validés strictement `> 0`. RabbitMQ définit `prefetch=0` comme
illimité; Arclith le refuse pour éviter qu'un worker accumule un nombre non borné de messages non
ackés.

## Handler

```python
from collections.abc import Mapping
from typing import Any

from arclith import CommandHandler


class CreateTodoCommandHandler(CommandHandler):
    command_type = "todo.create"

    def __init__(self, create_todo) -> None:
        self._create_todo = create_todo

    async def handle(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> None:
        command = CreateTodoCommand.model_validate(payload)
        await self._create_todo.execute(command)
```

Le handler peut lire `headers["correlation_id"]` et `headers["traceparent"]` pour relier logs,
traces et messages. L'adapter RabbitMQ ajoute `correlation_id` à la publication si l'appelant n'en
fournit pas; il propage `traceparent` quand un span OpenTelemetry courant existe.

## Worker

```python
from arclith import Arclith, CommandDispatcher

from app.application.create_todo import CreateTodoCommandHandler, create_todo_use_case

arclith = Arclith("config")
dispatcher = CommandDispatcher([
    CreateTodoCommandHandler(create_todo_use_case),
])


def _run_worker() -> None:
    arclith.run_command_bus(dispatcher)


if __name__ == "__main__":
    arclith.run_with_probes(_run_worker, transports=["command_bus"])
```

`run_command_bus()` est bloquant et adapté à un conteneur worker. En mode multi-transport, il peut
être passé à `run_with_probes()` comme les runners API/MCP.

## Publisher

```python
from arclith import Arclith

arclith = Arclith("config")
publisher = arclith.rabbitmq_command_bus()

await publisher.publish(
    "todo.create",
    {"title": "ecrire la documentation"},
    correlation_id="request-123",
)
```

Le channel aio-pika est ouvert avec `publisher_confirms` selon la config. Les messages sont publiés
en `application/json`, persistants, avec les headers `command_type`, `correlation_id` et
éventuellement `traceparent`.

## Ack, Retry Et DLX

| Situation | Action |
|---|---|
| Handler terminé sans exception | `ack()` après succès |
| Payload JSON invalide | `nack(requeue=false)` |
| Handler lève une exception | `nack(requeue=retry_requeue)` |

La configuration par défaut garde `retry_requeue=false`: les erreurs partent vers la DLX si
RabbitMQ l'a configurée sur la queue. Cela évite les boucles de requeue immédiate. Mettre
`retry_requeue=true` seulement pour un cas transitoire maîtrisé et monitoré.

## Smoke Docker Optionnel

Un test d'intégration réel peut être lancé contre RabbitMQ local:

```bash
docker run --rm -p 5672:5672 -p 15672:15672 rabbitmq:4-management
ARCLITH_RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/ \
  uv run --extra rabbitmq pytest tests/integration/test_rabbitmq_command_bus.py
```

Les tests unitaires Arclith utilisent des fakes et ne nécessitent pas RabbitMQ.

## Références

- RabbitMQ: [Consumer acknowledgements and publisher confirms](https://www.rabbitmq.com/docs/confirms)
- RabbitMQ: [Dead letter exchanges](https://www.rabbitmq.com/docs/dlx)
- aio-pika: [PyPI project](https://pypi.org/project/aio-pika/)
