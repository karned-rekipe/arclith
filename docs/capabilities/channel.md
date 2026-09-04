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
montre le wiring minimal ; les adapters webhook et Slack documenteront ensuite
leurs gestes de sécurité et de déploiement propres.

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
| `webhook` | HTTP signé générique | selon le store injecté | selon le store | prévu par #170 |
| `slack` | Slack Events API et réponses | selon le store injecté | selon le store | prévu par #171 |

Le catalogue CLI ne propose actuellement que `memory`. Les lignes `webhook` et
`slack` décrivent la trajectoire active ; elles ne sont pas encore installables
tant que leurs issues ne sont pas livrées. Telegram, Email et Teams restent hors
du périmètre actuel.

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter memory \
  --yes
```

La commande crée de façon idempotente :

```yaml
# config/adapters/bidirectional/memory.yaml
enabled: true
```

La configuration est chargée sous `adapters.channel.memory`. Le layout
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
| effets métier répétés | claim non atomique ou ID d'événement instable | corriger le `ChannelEventStore` et utiliser l'ID immuable du fournisseur |
| réponse non rejouée après erreur d'envoi | le handler a déjà réussi et le claim est conservé | utiliser un outbox ou une file outbound dédiée |

## Projet

Dans un service consommateur, garder l'implémentation de
`ChannelMessageHandler` dans `application/`, le resolver et le store partagés
dans des adapters outbound adaptés au déploiement, et le parsing HTTP/SDK dans
`adapters/bidirectional/<provider>/`. Aucun appel HTTP fournisseur ne doit
partir de `domain/`.

La suite active est le [webhook générique](https://github.com/karned-rekipe/arclith/issues/170),
puis [Slack Events API](https://github.com/karned-rekipe/arclith/issues/171).
