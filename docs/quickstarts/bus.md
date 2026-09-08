# Quickstart Bus

Ajouter la capability RabbitMQ et vérifier le bootstrap bus.

## Prérequis

- Python 3.13
- `uv`
- Docker

## Étapes

Si tu n'as pas encore de projet :

```bash
uvx --from arclith-cli arclith-cli init todo-bus --dir .
cd todo-bus
uv sync
```

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

Le scaffold crée `adapters/bidirectional/rabbitmq/` avec `bindings/`, `contracts/`,
`schemas/`, `policies/` et les modules register, codec, topology, consumer et publisher.
Le `main.py` issu d'`init` prend en charge `MODE=bus`. Ajouter un `CommandHandler`
dans les bindings et l'enregistrer explicitement dans `register.py`, puis lancer :

```bash
MODE=bus uv run python main.py
```

Le handler traduit le payload en commande applicative et appelle le même port
inbound que les autres transports. Voir le [blueprint complet](../deep-dives/adapter-blueprints.md).

## Nettoyage

```bash
docker rm -f arclith-rabbitmq
```

## Média

!!! note "Média à produire"
    Capture : console RabbitMQ Management.
    Vidéo : ajout de la capability puis lancement worker.

## Suite

Lire [Agent](agent.md), puis [command-bus/rabbitmq](../capabilities/command-bus.md).
