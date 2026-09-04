# Channel

La capability bidirectionnelle `channel` relie une messagerie externe à un
handler applicatif sans faire dépendre le domaine de son protocole ou de son
SDK. Elle normalise les messages entrants et sortants, résout explicitement
l'identité externe et déduplique les événements avant leur traitement.

## Intention

Utiliser `channel` pour recevoir une conversation depuis un webhook ou un
fournisseur de messagerie, appeler les use cases du service, puis renvoyer une
ou plusieurs réponses. Le contrat ne remplace ni un bus de commandes entre
services, ni une file de travaux durables.

## Channel N'est Pas Chat

`channel` est une frontière de transport : il authentifie un événement externe,
le normalise, résout son identité, le déduplique et achemine une réponse. Il ne
stocke ni transcript, ni historique de conversation, ni état d'agent.

Un chat est un comportement applicatif : il décide comment regrouper les
messages, conserver le contexte, appeler un LLM ou un agent et reprendre un
thread. Ces responsabilités restent dans le service consommateur, par exemple
derrière la capability `agent` et sa
[persistance de threads](agent-persistence.md), ou dans des entités et
repositories métier. `conversation_id` et `thread_id` sont seulement des
coordonnées provider-neutral transmises par `channel` ; elles ne créent aucune
persistance implicite.

## Position Hexagonale

```text
requête fournisseur
  -> adapter bidirectionnel (authentifie et normalise)
  -> ChannelDispatcher
       -> ChannelEventStore.claim()
       -> ChannelIdentityResolver.resolve()
       -> ChannelMessageHandler.handle()
       -> ChannelSender.send()
  -> accusé de réception fournisseur
```

Le domaine ne connaît ni FastAPI, ni Slack, ni un format de signature. Un
adapter fournisseur transforme son payload en `ChannelIncomingMessage` et
traduit le résultat du dispatcher vers le statut de transport approprié.

## Quickstart

Le [quickstart Channel](../quickstarts/channel.md) exécute le flux complet avec
l'adapter mémoire, sans compte externe ni dépendance optionnelle.

## Formation

Il n'existe pas encore de chapitre Channel dans le parcours Todo. Le quickstart
montre le wiring minimal ; les pages [Webhook](channel-webhook.md) et
[Slack](channel-slack.md) documentent ensuite leurs protocoles, leur sécurité
et leur déploiement.

## Contrat

### Modèles

| Type | Rôle |
|---|---|
| `ChannelIdentity` | identité externe affirmée par le fournisseur, encore non fiable pour l'application |
| `ResolvedChannelIdentity` | utilisateur et tenant applicatifs obtenus par mapping explicite |
| `ChannelIncomingMessage` | événement normalisé avec conversation, thread, texte ou pièces jointes |
| `ChannelOutgoingMessage` | réponse provider-neutral destinée au même canal ou à une autre conversation |
| `ChannelDeliveryReceipt` | résultat normalisé d'un envoi |
| `ChannelHandlerResult` | résultat synchrone (`completed`) ou prise en charge différée (`accepted`) |
| `ChannelDispatchResult` | résultat final `completed`, `accepted` ou `duplicate` |

Les modèles Pydantic sont stricts, immuables et refusent les champs inconnus.
Les timestamps doivent être timezone-aware et sont normalisés en UTC. Une pièce
jointe transporte une URL HTTP(S) sans credentials, query ou fragment, ou une
clé relative de la capability `storage`, jamais les octets ni un chemin absolu.
Les dictionnaires
`metadata` n'acceptent que des valeurs JSON ; chaque adapter doit en plus
n'y copier que sa liste blanche documentée.

### Ports

```python
from arclith import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelMessageHandler,
    ChannelSender,
)
```

- `ChannelMessageHandler` est le port inbound implémenté par l'application ;
- `ChannelIdentityResolver` interdit de traiter directement un identifiant
  fournisseur comme un identifiant métier ;
- `ChannelEventStore.claim()` réserve atomiquement `(provider, event_id)` avant
  tout appel applicatif ;
- `ChannelSender` envoie un `ChannelOutgoingMessage` et retourne un receipt.

`ChannelDispatcher` libère la réservation si la résolution d'identité ou le
handler échoue, afin qu'un retry puisse reprendre. Après un traitement
applicatif réussi, la réservation est conservée même si l'envoi de la réponse
échoue : rejouer automatiquement le handler pourrait dupliquer ses effets
métier. La reprise d'un envoi sortant doit donc être conçue séparément par le
service lorsque cette garantie est nécessaire.

### Erreurs

Les adapters exposent des erreurs communes :

- `InvalidChannelSignature` ;
- `ChannelUnauthorized` ;
- `UnsupportedChannelEvent` ;
- `ChannelIdentityNotResolved` ;
- `ChannelRateLimited`, avec un éventuel `retry_after_seconds` ;
- `ChannelDeliveryFailed` ;
- `ChannelUnavailable`.

Les erreurs ou payloads ne doivent jamais inclure de signature, token, contenu
de secret ou URL contenant des credentials.

## Adapters

| Adapter | Usage | Durable | Multi-processus | Production |
|---|---|---:|---:|---:|
| `memory` | tests, exemples et prototypes locaux | non | non | non |
| [`webhook`](channel-webhook.md) | HTTP générique, HMAC optionnel, réponse inline ou callback | selon le store injecté | selon le store | oui avec store partagé et secret |
| [`slack`](channel-slack.md) | Slack Events API HTTP et `chat.postMessage` | selon le store injecté | selon le store | oui avec store partagé et secrets |

Le catalogue CLI propose `memory`, `webhook` et `slack`. Telegram, Email et
Teams restent hors du périmètre actuel.

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter webhook \
  --yes
```

La commande crée de façon idempotente
`config/adapters/bidirectional/webhook.yaml`, ajoute l'extra
`arclith[channel]` et déclare le mapping de secret
`ARCLITH_WEBHOOK_SECRET`. Pour le fake local :

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter memory \
  --yes
```

Cette seconde commande crée :

```yaml
# config/adapters/bidirectional/memory.yaml
enabled: true
```

Pour Slack :

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter slack \
  --adapter-param workspace_id=T123ABC456 \
  --yes
```

La commande crée `config/adapters/bidirectional/slack.yaml`, ajoute les mappings
`ARCLITH_SLACK_SIGNING_SECRET` et `ARCLITH_SLACK_BOT_TOKEN`, sans écrire leurs
valeurs.

Les configurations sont chargées sous `adapters.channel.memory`,
`adapters.channel.webhook` et `adapters.channel.slack`. Le layout
canonique réserve `src/<package>/adapters/bidirectional/` aux adapters qui
assurent à la fois réception et envoi.

## Production

L'adapter mémoire conserve claims et messages dans un seul processus. Un
redémarrage oublie tout et plusieurs replicas ne partagent aucun état. Il ne
doit donc pas assurer l'idempotence d'un endpoint public.

Un adapter de production doit :

1. authentifier le corps brut avant parsing ;
2. borner la fraîcheur de la requête et résister au rejeu ;
3. utiliser un claim atomique partagé entre replicas ;
4. répondre dans le délai imposé par le fournisseur ;
5. mapper explicitement l'identité externe ;
6. limiter la taille du payload et des pièces jointes ;
7. appliquer timeout, backoff et `Retry-After` aux envois ;
8. journaliser uniquement IDs techniques, statuts et corrélation à cardinalité
   bornée.

`accepted` signifie que le service a durablement pris en charge le travail. Un
adapter ne doit donc pas renvoyer ce statut avant d'avoir réellement persisté
ou publié la suite du traitement.

## Validation

```bash
uv run pytest -q \
  tests/units/domain/models/test_channel.py \
  tests/units/application/test_channel.py \
  tests/units/adapters/bidirectional/memory/test_channel.py \
  tests/units/infrastructure/test_channel_factory.py

cd cli
uv run --frozen pytest -q \
  tests/test_capabilities.py \
  tests/test_add_adapter.py
```

Vérifier aussi `make coverage`, `make precommit` et `make docs` avant livraison.

## Troubleshooting

| Symptôme | Cause probable | Action |
|---|---|---|
| `ChannelIdentityNotResolved` | aucun mapping exact pour l'identité externe | enregistrer ou injecter le mapping applicatif attendu |
| résultat `duplicate` au premier essai visible | l'ID fournisseur a déjà été claim, éventuellement par un autre replica | corréler avec `provider_event_id` et inspecter le store partagé |
| `adapters.channel.memory.enabled=true is required` | fichier absent ou adapter désactivé | générer `channel/memory` ou corriger le YAML scoped |
| réponse webhook `401` | secret absent côté appelant, timestamp périmé ou signature différente du corps brut | recalculer la signature avec le timestamp et les octets exacts envoyés |
| réponse webhook `500 response_mode_error` | résultat du handler incompatible avec `sync` ou `accepted` | retourner `completed` en `sync`, ou persister/publier puis retourner `accepted` |
| réponse Slack `401` | signature `v0` absente, invalide ou périmée | vérifier le Signing Secret, l'horloge et le corps brut |
| réponse Slack `403` | identité non mappée ou workspace/canal refusé | corriger le resolver ou les allowlists sans exposer le token |
| réponse Slack `429` | `chat.postMessage` est limité | appliquer `Retry-After` dans une reprise outbound dédiée |
| effets métier répétés | claim non atomique ou ID d'événement instable | corriger le `ChannelEventStore` et utiliser l'ID immuable du fournisseur |
| réponse non rejouée après erreur d'envoi | le handler a déjà réussi et le claim est conservé | utiliser un outbox ou une file outbound dédiée |

## Projet

Dans un service consommateur, garder l'implémentation de
`ChannelMessageHandler` dans `application/`, le resolver et le store partagés
dans des adapters outbound adaptés au déploiement, et le parsing HTTP/SDK dans
`adapters/bidirectional/<provider>/`. Aucun appel HTTP fournisseur ne doit
partir de `domain/`.

Consulter les guides du [webhook générique](channel-webhook.md) et de
[Slack Events API](channel-slack.md) pour leurs contrats de transport.
