# Quickstart Channel

Ajouter le fake mémoire et vérifier un message entrant, sa résolution
d'identité et sa réponse, sans service externe.

## Prérequis

- Python 3.13 ;
- `uv`.

## Ajouter La Capability

Depuis un projet Arclith existant :

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter memory \
  --yes
```

La commande crée `config/adapters/bidirectional/memory.yaml`.

## Exécuter Le Flux

```bash
uv run python - <<'PY'
import asyncio

from arclith import (
    ChannelDispatcher,
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelIncomingMessage,
    ChannelMessageHandler,
    ChannelOutgoingMessage,
    MemoryChannel,
    MemoryChannelIdentityResolver,
    ResolvedChannelIdentity,
)


class EchoHandler(ChannelMessageHandler):
    async def handle(self, message, identity):
        return ChannelHandlerResult(
            responses=(
                ChannelOutgoingMessage(
                    channel=message.channel,
                    conversation_id=message.conversation_id,
                    thread_id=message.thread_id,
                    text=f"Reçu pour {identity.user_id}: {message.text}",
                ),
            )
        )


async def main():
    external = ChannelIdentity(
        provider="memory",
        external_user_id="external-42",
    )
    resolver = MemoryChannelIdentityResolver()
    resolver.register(
        external,
        ResolvedChannelIdentity(user_id="user-42", tenant_id="tenant-demo"),
    )
    channel = MemoryChannel()
    dispatcher = ChannelDispatcher(EchoHandler(), resolver, channel, channel)

    message = ChannelIncomingMessage(
        channel="memory",
        provider_event_id="event-1",
        conversation_id="conversation-1",
        sender=external,
        text="bonjour",
    )
    result = await dispatcher.dispatch(message)
    duplicate = await dispatcher.dispatch(message)

    assert result.status == "completed"
    assert result.identity.user_id == "user-42"
    assert result.receipts[0].status == "delivered"
    assert channel.sent_messages[0].text == "Reçu pour user-42: bonjour"
    assert duplicate.status == "duplicate"
    print("channel memory: OK")


asyncio.run(main())
PY
```

## Valider Le Bootstrap

```bash
uv run python - <<'PY'
from arclith import Arclith, MemoryChannel

app = Arclith("config")
assert app.config.adapters.channel.configured_adapters() == ("memory",)
assert isinstance(app.channel_sender("memory"), MemoryChannel)
print("channel config: OK")
PY
```

## Résultat

Le premier dispatch appelle le handler et enregistre une réponse. Le second
retourne `duplicate` sans rappeler l'application.

## Limite

Le fake mémoire est mono-processus et non durable. Pour un endpoint public,
injecter un `ChannelEventStore` atomique partagé et suivre les exigences de la
[capability Channel](../capabilities/channel.md).

## Suite

Lire la [référence Channel](../capabilities/channel.md), puis raccorder le
[webhook générique signé](../capabilities/channel-webhook.md).
