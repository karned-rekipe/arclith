# Capability Command Bus

Bus de commandes applicatives use-case first.

## Adapter

| Adapter | Usage |
|---|---|
| `rabbitmq` | worker et publisher RabbitMQ |

## Commande

```bash
uv add "arclith[rabbitmq]"
arclith-cli add-adapter --capability command-bus --adapter rabbitmq --yes
```

## Configuration

```yaml
# config/command_bus.yaml
enabled:
  - rabbitmq
rabbitmq:
  url: "amqp://guest:guest@127.0.0.1:5672/"
  exchange: "arclith.commands"
  queue: "arclith.commands"
```

## Règle

Un handler RabbitMQ valide le message puis appelle un use case. Il ne contient pas le métier lui-même.

## Validation Bootstrap

```bash
uv run python - <<'PY'
from arclith import Arclith

app = Arclith("config")
assert app.config.command_bus.is_enabled("rabbitmq")
print(app.config.command_bus.rabbitmq.exchange)
PY
```

Le runner worker appartient au projet consommateur. Voir la référence dédiée pour le câblage
`CommandHandler` et `CommandDispatcher`.

## Suite

Lire [Command Bus RabbitMQ](../command-bus.md).
