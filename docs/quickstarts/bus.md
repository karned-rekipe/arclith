# Quickstart Bus

Ajouter la capability RabbitMQ et vérifier le bootstrap bus.

## Prérequis

- Python 3.13
- `uv`
- Docker

## Étapes

```bash
docker run --rm -d --name arclith-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:4-management
```

Dans le projet Arclith :

```bash
uv add "arclith[rabbitmq]"
uvx --from arclith-cli arclith-cli add-adapter \
  --capability command-bus \
  --adapter rabbitmq \
  --yes
```

## Validation Bootstrap

```bash
uv run python - <<'PY'
from arclith import Arclith

app = Arclith("config")
assert app.config.command_bus.is_enabled("rabbitmq")
print(app.config.command_bus.rabbitmq.queue)
PY
```

## Résultat

La configuration bus est chargée et RabbitMQ est actif côté Arclith.

## Runner Projet

Pour consommer réellement des messages, le projet doit ajouter un `CommandHandler`, un
`CommandDispatcher`, puis appeler `arclith.run_command_bus(dispatcher)`.

## Nettoyage

```bash
docker rm -f arclith-rabbitmq
```

## Média

!!! note "Média à produire"
    Capture : console RabbitMQ Management.
    Vidéo : ajout de la capability puis lancement worker.

## Suite

Lire [command-bus/rabbitmq](../capabilities/command-bus.md).
