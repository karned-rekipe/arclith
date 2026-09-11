# Quickstart Bus

Créer un projet neuf, exposer le use case comme commande RabbitMQ et vérifier
qu'un vrai message atteint le port applicatif.

## Prérequis

- Python 3.13 ;
- [`uv`](https://docs.astral.sh/uv/) ;
- Docker ;
- `uv tool install arclith-cli` ;
- `arclith-cli version` pour vérifier que la commande est disponible.

## Étapes

```bash
arclith-cli init todo-bus --dir .
cd todo-bus
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability command-bus --adapter rabbitmq --yes
arclith-cli expose-usecase create-todo --via rabbitmq --feature todos \
  --command-type todo.create.v1
uv sync
uv run python -m pytest
```

Le CLI ajoute lui-même l'extra `arclith[rabbitmq]` et crée uniquement le
blueprint RabbitMQ sélectionné.

## Broker local

```bash
docker run --rm -d --name arclith-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:4-management
MODE=bus uv run python main.py
```

Publier ensuite une commande avec `Arclith.rabbitmq_command_bus().publish` en
utilisant le type `todo.create.v1` et un payload `{}`. Le smoke end to end doit
attendre la consommation, vérifier l'ACK et fermer proprement publisher et
consumer. Pour un test automatisé, voir
[Capability Command Bus](../capabilities/command-bus.md#validation-locale).

## Arborescence

Le scaffold crée `adapters/bidirectional/rabbitmq/` avec `bindings`,
`contracts`, `schemas`, `policies` et les modules `register`, `codec`,
`topology`, `consumer`, `publisher`, `dependencies`. Seul
`bindings/create_todo.py` contient le mapping de cette opération.

## Nettoyage

```bash
docker stop arclith-rabbitmq
```

## Suite

Lire [Agent](agent.md), puis [command-bus/rabbitmq](../capabilities/command-bus.md).
