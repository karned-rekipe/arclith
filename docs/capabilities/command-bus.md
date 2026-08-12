# Capability Command Bus

Bus de commandes applicatives use-case first.

## Objectif

Le command bus transporte des commandes entre services ou processus. Il reste
orienté use case: le message est validé, décodé, puis dispatché vers un handler
applicatif.

## Adapter

| Adapter | Usage |
|---|---|
| `rabbitmq` | worker et publisher RabbitMQ |

## Commande

```bash
uv add "arclith[rabbitmq]"
arclith-cli add-adapter --capability command-bus --adapter rabbitmq --yes
```

## Configuration Générée

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

## Publier

```python
from arclith import Arclith

app = Arclith("config")
bus = app.rabbitmq_command_bus()

await bus.publish(
    "todo.create",
    {"title": "Documenter le bus"},
    correlation_id="demo-1",
)
await bus.close()
```

Le publisher ajoute `command_type`, `correlation_id` et, si disponible,
`traceparent`.

## Consommer

```python
from arclith.application.command_bus import CommandDispatcher

dispatcher = CommandDispatcher()
dispatcher.register("todo.create", CreateTodoCommandHandler(create_todo_use_case))

app.run_command_bus(dispatcher)
```

Le handler reçoit une `CommandEnvelope`, valide son payload, puis appelle un use
case. Il ne doit pas contenir de logique métier lourde.

## Garanties

| Sujet | Comportement |
|---|---|
| Ack | `ack()` après dispatch réussi |
| Message invalide | `nack(requeue=False)` |
| Erreur handler | `nack()` selon `retry_enabled` et `retry_requeue` |
| Backpressure | `prefetch` et `concurrency` bornent le travail |
| Publication | `publisher_confirms` activé par défaut |
| Rejet durable | DLX configurable |

## Règles

- Définir un `command_type` stable et versionnable.
- Toujours propager `correlation_id`.
- Garder les handlers idempotents quand la commande peut être rejouée.
- Ne pas requeue à l'infini sans DLX ni stratégie d'alerte.
- Ne pas exposer de secret dans les headers ou payloads.

## Validation Bootstrap

```bash
uv run python - <<'PY'
from arclith import Arclith

app = Arclith("config")
assert app.config.command_bus.is_enabled("rabbitmq")
print(app.config.command_bus.rabbitmq.exchange)
PY
```

## Validation Locale

```bash
docker run --rm -d --name arclith-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:4-management

uv run pytest
docker stop arclith-rabbitmq
```

Un smoke complet doit publier une commande, vérifier le handler, puis inspecter
ack/DLX selon le scénario.

## Suite

Lire [Deep Dive Bus](../deep-dives/bus.md), puis [Command Bus RabbitMQ](../command-bus.md).
