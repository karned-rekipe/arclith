# Channel Slack

L'adapter bidirectionnel `channel/slack` reçoit les événements Slack Events API
par HTTP, vérifie leur signature sur le corps brut, normalise les messages dans
le contrat `channel`, puis publie les réponses texte avec
`chat.postMessage`. Il n'ajoute ni SDK Slack ni logique conversationnelle dans
le domaine.

## Intention

Utiliser cet adapter pour connecter une Slack App à un handler ou un agent
Arclith. La v1 couvre les Request URLs HTTP, `url_verification`, `message`,
`app_mention` et les réponses texte dans le thread d'origine.

Socket Mode, les slash commands, les block actions et l'installation OAuth
multi-workspace automatisée restent hors scope. `channel/slack` transporte les
messages ; le transcript et l'état d'agent restent des responsabilités
applicatives, conformément à [Channel n'est pas Chat](channel.md#channel-nest-pas-chat).

## Position Hexagonale

```text
Slack Events API
  -> POST signé sur /channels/slack/events
  -> SlackChannelAdapter
       -> taille, media type, signature v0 et fenêtre de fraîcheur
       -> challenge ou filtrage des événements
       -> normalisation ChannelIncomingMessage
       -> ChannelDispatcher
            -> ChannelEventStore.claim("slack", event_id)
            -> ChannelIdentityResolver.resolve()
            -> ChannelMessageHandler.handle()
            -> SlackChannelSender.chat.postMessage()
  -> HTTP 200 pour l'accusé Slack
```

FastAPI, les headers Slack et `httpx` restent dans l'adapter. Les modèles et
ports communs dans `domain/` ne dépendent pas du fournisseur.

## Quickstart

### Ajouter L'adapter

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter slack \
  --adapter-param workspace_id=T123ABC456 \
  --yes
```

La commande :

- crée `config/adapters/bidirectional/slack.yaml` ;
- ajoute l'extra `arclith[channel]`, qui fournit `httpx` ;
- crée les mappings `ARCLITH_SLACK_SIGNING_SECRET` et
  `ARCLITH_SLACK_BOT_TOKEN` dans `config/secrets.yaml` ;
- ne place aucun token dans un fichier versionné.

Le fichier scoped généré est chargeable avant que les secrets soient fournis :

```yaml
enabled: true
path: /channels/slack/events
signing_secret: null
bot_token: null
workspace_id: T123ABC456
allowed_channel_ids: []
signature_tolerance_seconds: 300
event_ttl_seconds: 86400
max_payload_bytes: 1048576
request_timeout_seconds: 5.0
```

Par défaut, le montage du router construit aussi le sender Slack : il exige donc
`signing_secret` **et** `bot_token`, puis vérifie immédiatement la présence de
l'extra `channel`. Si le service injecte explicitement un `sender` personnalisé,
seul `signing_secret` est requis par l'adapter entrant. Dans les deux cas, une
configuration requise manquante échoue au démarrage, pas lors du premier
événement.

### Brancher Le Router

Le handler doit recopier `conversation_id` et `thread_id` dans sa réponse pour
répondre dans le canal et le thread Slack d'origine :

```python
import os

from fastapi import FastAPI

from arclith import (
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelMessageHandler,
    ChannelOutgoingMessage,
    MemoryChannel,
    MemoryChannelIdentityResolver,
    ResolvedChannelIdentity,
    SlackChannelSettings,
    build_slack_router,
)


class EchoHandler(ChannelMessageHandler):
    async def handle(self, message, identity):
        return ChannelHandlerResult(
            responses=(
                ChannelOutgoingMessage(
                    channel="slack",
                    conversation_id=message.conversation_id,
                    thread_id=message.thread_id,
                    text=f"Reçu pour {identity.user_id}: {message.text}",
                ),
            )
        )


settings = SlackChannelSettings(
    signing_secret=os.environ["ARCLITH_SLACK_SIGNING_SECRET"],
    bot_token=os.environ["ARCLITH_SLACK_BOT_TOKEN"],
    workspace_id="T123ABC456",
    allowed_channel_ids=("C123ABC456",),
)
resolver = MemoryChannelIdentityResolver()
resolver.register(
    ChannelIdentity(
        provider="slack",
        external_user_id="U123ABC456",
        external_tenant_id="T123ABC456",
        external_workspace_id="T123ABC456",
    ),
    ResolvedChannelIdentity(user_id="user-42", tenant_id="tenant-demo"),
)
event_store = MemoryChannel()

app = FastAPI()
app.include_router(
    build_slack_router(settings, EchoHandler(), resolver, event_store)
)
```

`MemoryChannel` ne convient qu'au test local. En production, injecter un
`ChannelEventStore` atomique partagé entre les replicas et un resolver
d'identité tenant-aware.

Avec le bootstrap Arclith, utiliser normalement les settings déjà résolus :

```python
settings = arclith.config.adapters.channel.slack
if settings is not None and settings.enabled:
    fastapi_app.include_router(
        build_slack_router(settings, handler, resolver, event_store)
    )
```

Pour un worker sortant, `arclith.channel_sender("slack")` construit le même
`SlackChannelSender` à partir de la configuration.

### Tester Le Challenge Localement

Slack signe la chaîne `v0:<timestamp>:<corps-brut>` avec HMAC-SHA256. Le corps
calculé doit être envoyé sans nouvelle sérialisation :

```bash
export ARCLITH_SLACK_SIGNING_SECRET='replace-with-the-slack-signing-secret'
SLACK_BODY='{"type":"url_verification","challenge":"local-challenge"}'
SLACK_TIMESTAMP=$(date +%s)
export SLACK_BODY SLACK_TIMESTAMP

SLACK_SIGNATURE=$(python - <<'PY'
import hashlib
import hmac
import os

secret = os.environ["ARCLITH_SLACK_SIGNING_SECRET"].encode()
timestamp = os.environ["SLACK_TIMESTAMP"]
body = os.environ["SLACK_BODY"].encode()
basestring = b"v0:" + timestamp.encode() + b":" + body
print("v0=" + hmac.new(secret, basestring, hashlib.sha256).hexdigest())
PY
)

curl -fsS http://127.0.0.1:8000/channels/slack/events \
  -H 'Content-Type: application/json' \
  -H "X-Slack-Request-Timestamp: $SLACK_TIMESTAMP" \
  -H "X-Slack-Signature: $SLACK_SIGNATURE" \
  --data-binary "$SLACK_BODY"
```

La réponse attendue est `{"challenge":"local-challenge"}`. Le challenge est
authentifié mais ne déclenche ni resolver, ni claim, ni handler.

## Formation

Commencer par le [quickstart Channel](../quickstarts/channel.md) pour comprendre
les quatre ports et l'idempotence sans fournisseur. Cette page ajoute le
protocole Slack, la signature et les contraintes d'acquittement.

## Événements Entrants

L'enveloppe externe tolère les champs additionnels de Slack pour rester
compatible avec les évolutions du fournisseur. Les champs utilisés sont typés
et seuls les éléments documentés ci-dessous traversent la frontière.

| Événement | Traitement |
|---|---|
| `url_verification` | retourne le challenge signé, sans dispatch |
| `event_callback` + `message` | normalise un message utilisateur |
| `event_callback` + `app_mention` | normalise une mention de l'application |
| événement non supporté | retourne `200` avec `status: ignored` |
| événement avec `bot_id`, `app_id` ou subtype non supporté | retourne `200` avec `status: ignored` |

Les messages `file_share` sont acceptés. Chaque fichier devient un
`ChannelAttachment(kind="slack_file")` avec nom, MIME type, taille, URL privée
HTTPS et `slack_file_id`. L'adapter ne télécharge jamais le fichier et ne met
jamais le bot token dans son URL. Les autres subtypes, notamment édition,
suppression et `bot_message`, sont ignorés pour éviter les boucles et les
événements non conversationnels.

La normalisation produit :

| Champ commun | Source Slack |
|---|---|
| `provider_event_id` | `event_id` de l'enveloppe |
| `conversation_id` | `event.channel` |
| `thread_id` | `event.thread_ts`, sinon `event.ts` pour créer un thread racine |
| `sender.external_user_id` | `event.user` |
| `sender.external_workspace_id` | `team_id` |
| `sender.external_tenant_id` | `enterprise_id`, sinon `team_id` |
| `text` | `event.text` non vide |
| `attachments` | fichiers Slack supportés, sans contenu binaire |
| `metadata` | `event_type`, `event_ts`, `retry_num`, `retry_reason` uniquement |

Les identifiants Slack restent des affirmations externes. Ils ne deviennent
jamais directement un user ou tenant applicatif : le
`ChannelIdentityResolver` doit retourner un `ResolvedChannelIdentity` explicite.

## Réponses Sortantes

`SlackChannelSender` appelle uniquement l'URL fixe
`https://slack.com/api/chat.postMessage`, sans suivre de redirection. Il envoie
le token dans `Authorization: Bearer`, jamais dans l'URL ou le corps.

La v1 prend en charge les réponses texte. Elle transmet :

- `conversation_id` comme `channel` ;
- `thread_id` comme `thread_ts` ;
- `message_id` comme `client_msg_id` ;
- `text` comme contenu du message.

Les pièces jointes sortantes sont refusées explicitement. Un envoi réussi
retourne un `ChannelDeliveryReceipt` dont `provider_message_id` est le `ts`
Slack. Les textes de plus de 40 000 caractères sont refusés avant l'appel. Si
`allowed_channel_ids` est configuré, le sender applique la même allowlist aux
messages sortants afin qu'un handler ne puisse pas contourner la restriction
inbound.

## Acquittement Et Idempotence

Slack attend une réponse HTTP 2xx en moins de trois secondes et retente les
événements non acquittés. L'endpoint retourne toujours `200` pour un challenge,
un événement ignoré, un doublon, un traitement terminé ou une prise en charge
durable.

Le statut `accepted` n'est émis que si le handler a déjà persisté ou publié le
travail dans une infrastructure durable. Pour les traitements longs, le
handler doit donc mettre le message en file puis retourner
`ChannelHandlerResult(status="accepted")`. Une simple tâche locale FastAPI ne
constitue pas cette garantie.

Le dispatcher claim atomiquement `("slack", event_id)` avant la résolution
d'identité. Les retries portant le même `event_id` obtiennent
`status: duplicate` sans rejouer le handler.

Après une réussite du handler, une erreur `chat.postMessage` ne libère pas le
claim : cela évite de répéter des effets métier. Une réponse critique doit être
écrite dans un outbox ou une file outbound et retentée séparément.

## Configuration Slack

Dans la Slack App :

1. activer Event Subscriptions et configurer la Request URL HTTPS vers le path
   du router ;
2. souscrire `app_mention` et/ou les variantes `message.*` nécessaires ;
3. installer l'application dans le workspace ;
4. exposer le Signing Secret et le Bot User OAuth Token via la capability
   `secrets` ;
5. réinstaller l'application après tout changement de scopes.

Scopes minimaux selon les subscriptions choisies :

| Besoin | Scope bot |
|---|---|
| recevoir les mentions | `app_mentions:read` |
| lire les messages de canaux publics | `channels:history` |
| lire les messages de canaux privés | `groups:history` |
| lire les messages directs | `im:history` |
| lire les messages directs de groupe | `mpim:history` |
| envoyer une réponse | `chat:write` |
| publier dans un canal public sans invitation | `chat:write.public`, optionnel |
| télécharger ultérieurement un fichier privé | `files:read`, hors de cet adapter |

Limiter `workspace_id` en mono-workspace et renseigner
`allowed_channel_ids` dès que le service n'a pas vocation à répondre partout.
Une liste vide autorise tous les canaux du workspace accepté.

Références officielles : [Events API](https://docs.slack.dev/apis/events-api/),
[vérification des requêtes](https://docs.slack.dev/authentication/verifying-requests-from-slack/),
[`app_mention`](https://docs.slack.dev/reference/events/app_mention/) et
[`chat.postMessage`](https://docs.slack.dev/reference/methods/chat.postMessage/).

## Statuts HTTP

Le router déclare explicitement toutes ses réponses OpenAPI :

| HTTP | Code JSON | Cause |
|---:|---|---|
| `200` | — | challenge, terminé, accepted, duplicate ou ignored |
| `400` | `invalid_payload` | JSON ou enveloppe Slack invalide |
| `401` | `invalid_signature` | signature absente, invalide ou vieille de plus de la tolérance |
| `403` | `identity_not_resolved`, `channel_unauthorized` | identité, workspace, canal ou credentials refusés |
| `413` | `payload_too_large` | stream supérieur à `max_payload_bytes` |
| `415` | `unsupported_media_type` | media type différent de `application/json` |
| `422` | `invalid_event` | événement supporté mais champs invalides |
| `429` | `slack_rate_limited` | Web API limitée ; `Retry-After` numérique est propagé |
| `502` | `delivery_failed` | `chat.postMessage` refuse le message ou répond de façon invalide |
| `503` | `slack_unavailable` | timeout, transport, erreur 5xx ou erreur Slack transitoire |

Les détails sont stables et ne reprennent jamais le corps Slack, une signature,
un token ou un message complet.

## Sécurité

- Le stream HTTP est borné avant le parsing.
- La signature `v0` est calculée sur les octets bruts et comparée avec
  `hmac.compare_digest`.
- Les requêtes hors de `signature_tolerance_seconds` sont rejetées.
- `signing_secret` et `bot_token` utilisent `SecretStr` et ne sont pas rendus
  en clair par les settings.
- L'endpoint Web API est constant ; ni le payload entrant ni la réponse du
  handler ne peuvent choisir une URL.
- Les redirects sortantes sont désactivées et le timeout est borné.
- Les payloads complets, textes, signatures et tokens ne sont jamais loggés par
  l'adapter.
- Les fichiers privés ne sont pas téléchargés ; un téléchargement ultérieur
  doit appliquer auth, taille, MIME type, timeout et stockage sûr.

## Production

Avant d'exposer la Request URL :

1. injecter les deux secrets depuis Vault ou des variables d'environnement ;
2. restreindre workspace et canaux ;
3. utiliser un event store atomique partagé ;
4. garantir un acquittement sous trois secondes avec un handler durable court ;
5. isoler la reprise outbound dans un outbox si la réponse est critique ;
6. appliquer une politique egress limitée à Slack ;
7. journaliser uniquement IDs techniques, statut, latence et corrélation à
   cardinalité bornée.

## Validation

```bash
uv run pytest -q \
  tests/units/adapters/bidirectional/slack \
  tests/units/infrastructure/test_channel_settings.py \
  tests/units/infrastructure/test_channel_factory.py

cd cli
uv run --frozen pytest -q \
  tests/test_capabilities.py \
  tests/test_add_adapter.py
```

Vérifier ensuite `make quality`, `make precommit`, les deux lockfiles et
`make docs`.

## Troubleshooting

| Symptôme | Diagnostic | Correction |
|---|---|---|
| `401 invalid_signature` | timestamp périmé ou corps modifié avant vérification | vérifier l'horloge et lire le corps brut avant tout parsing |
| échec au montage pour `signing_secret` | secret non résolu | vérifier le mapping `ARCLITH_SLACK_SIGNING_SECRET` |
| échec du sender pour `bot_token` | token absent | vérifier `ARCLITH_SLACK_BOT_TOKEN` et l'installation de l'app |
| `403 identity_not_resolved` | tuple user/enterprise/workspace non mappé | créer le mapping explicite dans le resolver |
| `403 channel_unauthorized` | workspace ou canal hors allowlist, ou token refusé | vérifier la configuration et les scopes sans afficher le token |
| `duplicate` | `event_id` déjà claim après un retry Slack | ne pas régénérer l'ID ; inspecter le store partagé |
| `429` | limite `chat.postMessage` | respecter `Retry-After` dans la reprise outbound |
| `502` ou `503` | refus ou indisponibilité Slack | corréler l'event ID et utiliser un outbox pour les réponses critiques |

## Projet

Garder `ChannelMessageHandler` dans `application/`, le mapping d'identité et le
store partagé derrière leurs ports, et le router Slack dans le bootstrap
FastAPI. Ne placer aucun appel Slack, secret, parsing de payload ou règle de
thread dans `domain/`.
