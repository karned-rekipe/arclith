# Channel Webhook

L'adapter bidirectionnel `channel/webhook` reçoit un JSON HTTP générique, vérifie
son authenticité sur les octets bruts, le transforme en
`ChannelIncomingMessage`, puis passe par le `ChannelDispatcher`. Il n'impose ni
fournisseur, ni SDK, ni logique métier.

## Intention

Utiliser cet adapter pour raccorder un outil interne, une automatisation ou un
prototype qui sait émettre un webhook HTTP. Préférer un adapter fournisseur
dédié lorsqu'un protocole impose ses propres challenges, événements ou règles
d'accusé de réception.

Le webhook transporte un message. Il ne devient pas pour autant un historique
de chat : consulter la distinction [Channel n'est pas Chat](channel.md#channel-nest-pas-chat).

## Position Hexagonale

```text
POST JSON signé
  -> WebhookChannelAdapter
       -> contrôle taille, media type, HMAC et event ID
       -> normalisation provider-neutral
       -> ChannelDispatcher
            -> ChannelEventStore
            -> ChannelIdentityResolver
            -> ChannelMessageHandler
            -> réponse inline ou WebhookCallbackSender
  -> réponse HTTP explicite
```

FastAPI reste dans l'adapter. Le handler applicatif reçoit uniquement les
modèles communs `channel`, et `domain/` ne dépend ni de FastAPI ni de `httpx`.

## Quickstart

### Installer L'adapter

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability channel \
  --adapter webhook \
  --yes
```

La commande :

- crée `config/adapters/bidirectional/webhook.yaml` ;
- ajoute l'extra `channel` à la dépendance Arclith du projet ;
- crée dans `config/secrets.yaml` le mapping
  `adapters.channel.webhook.secret: ARCLITH_WEBHOOK_SECRET` ;
- ne place aucune valeur de secret dans un fichier versionné.

Le YAML généré utilise le mode synchrone :

```yaml
enabled: true
path: /channels/webhook
secret: null
signature_header: X-Arclith-Signature
timestamp_header: X-Arclith-Timestamp
signature_tolerance_seconds: 300
idempotency_header: X-Arclith-Event-Id
event_ttl_seconds: 86400
max_payload_bytes: 1048576
metadata_allowlist: []
response_mode: sync
callback_url: null
callback_allowed_host: null
callback_timeout_seconds: 5.0
```

Pour un endpoint exposé, fournir un secret aléatoire d'au moins 32 octets via
le resolver `secrets`. `secret: null` désactive volontairement HMAC et convient
uniquement à un test local ou à une autre frontière déjà authentifiée.

### Brancher Le Router

Ce POC utilise les implémentations mémoire afin de rester exécutable. En
production, remplacer le resolver et surtout le store d'événements par des
adapters partagés entre replicas.

```python
from fastapi import FastAPI

from arclith import (
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelMessageHandler,
    ChannelOutgoingMessage,
    MemoryChannel,
    MemoryChannelIdentityResolver,
    ResolvedChannelIdentity,
    WebhookChannelSettings,
    build_webhook_router,
)


class EchoHandler(ChannelMessageHandler):
    async def handle(self, message, identity):
        return ChannelHandlerResult(
            responses=(
                ChannelOutgoingMessage(
                    channel="webhook",
                    conversation_id=message.conversation_id,
                    thread_id=message.thread_id,
                    text=f"Reçu pour {identity.user_id}: {message.text}",
                ),
            )
        )


settings = WebhookChannelSettings(
    secret="replace-with-a-secret-of-at-least-32-bytes",
    metadata_allowlist=("trace_id",),
)
resolver = MemoryChannelIdentityResolver()
resolver.register(
    ChannelIdentity(provider="webhook", external_user_id="external-42"),
    ResolvedChannelIdentity(user_id="user-42", tenant_id="tenant-demo"),
)
event_store = MemoryChannel()

app = FastAPI()
app.include_router(
    build_webhook_router(settings, EchoHandler(), resolver, event_store)
)
```

Dans une application Arclith, utiliser normalement les settings déjà chargés :

```python
settings = arclith.config.adapters.channel.webhook
if settings is not None and settings.enabled:
    fastapi_app.include_router(
        build_webhook_router(settings, handler, resolver, event_store)
    )
```

### Envoyer Un Événement Signé

La signature canonique est :

```text
sha256=HMAC-SHA256(secret, "<timestamp>.<corps-brut>")
```

Le corps signé doit être exactement celui envoyé, octet pour octet. Cet exemple
évite de mettre le secret dans la ligne de commande :

```bash
export ARCLITH_WEBHOOK_SECRET='replace-with-a-random-secret-of-at-least-32-bytes'
WEBHOOK_BODY='{"sender_id":"external-42","conversation_id":"conversation-1","text":"bonjour","metadata":{"trace_id":"demo-1","ignored":"drop-me"}}'
WEBHOOK_TIMESTAMP=$(date +%s)
export WEBHOOK_BODY WEBHOOK_TIMESTAMP

WEBHOOK_SIGNATURE=$(python - <<'PY'
import hashlib
import hmac
import os

secret = os.environ["ARCLITH_WEBHOOK_SECRET"].encode()
timestamp = os.environ["WEBHOOK_TIMESTAMP"]
body = os.environ["WEBHOOK_BODY"].encode()
digest = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256)
print("sha256=" + digest.hexdigest())
PY
)

curl -fsS http://127.0.0.1:8000/channels/webhook \
  -H 'Content-Type: application/json' \
  -H "X-Arclith-Event-Id: event-demo-1" \
  -H "X-Arclith-Timestamp: $WEBHOOK_TIMESTAMP" \
  -H "X-Arclith-Signature: $WEBHOOK_SIGNATURE" \
  --data-binary "$WEBHOOK_BODY" | python -m json.tool
```

Une réponse synchrone réussie contient les messages provider-neutral à rendre
au client :

```json
{
  "status": "completed",
  "responses": [
    {
      "message_id": "0199...",
      "channel": "webhook",
      "conversation_id": "conversation-1",
      "thread_id": null,
      "recipient_id": null,
      "text": "Reçu pour user-42: bonjour",
      "attachments": [],
      "reply_to": null,
      "metadata": {}
    }
  ],
  "receipts": [
    {
      "message_id": "0199...",
      "provider_message_id": null,
      "status": "accepted",
      "timestamp": "2026-09-04T12:00:00Z",
      "metadata": {}
    }
  ]
}
```

## Formation

Le [quickstart Channel](../quickstarts/channel.md) explique d'abord les quatre
ports avec le fake mémoire. Cette page ajoute ensuite le geste HTTP, HMAC et
les contraintes de production.

## Payload Entrant

Le JSON est strict : tout champ inconnu est rejeté.

| Champ | Requis | Description |
|---|---:|---|
| `sender_id` | oui | identifiant externe, résolu ensuite par `ChannelIdentityResolver` |
| `conversation_id` | oui | conversation externe stable |
| `text` | conditionnel | texte non vide ; requis si aucune pièce jointe |
| `sender_display_name` | non | libellé externe non fiable |
| `external_tenant_id` | non | tenant affirmé par l'émetteur, à mapper explicitement |
| `external_workspace_id` | non | workspace affirmé par l'émetteur |
| `thread_id` | non | thread externe, sans persistance implicite |
| `attachments` | non | métadonnées `ChannelAttachment`, jamais des octets embarqués |
| `metadata` | non | JSON fini ; seules les clés de `metadata_allowlist` sont transmises |

L'identifiant d'événement n'est pas accepté dans le JSON. Il vient uniquement
du header `idempotency_header`, afin de conserver une source stable et
configurée côté serveur.

## Modes De Réponse

| Mode | Résultat handler valide | HTTP | Livraison |
|---|---|---:|---|
| `sync` | `completed` | `200` | les réponses sont retournées dans le corps HTTP |
| `accepted` | `accepted` | `202` | le handler confirme avoir persisté ou publié durablement la suite |
| `callback` | `completed` | `200` | les réponses sont POSTées immédiatement vers l'URL serveur |
| `callback` | `accepted` | `202` | le handler a pris le travail durablement et livrera plus tard via `WebhookCallbackSender` |

Un résultat `accepted` ne déclenche aucune tâche FastAPI locale. Le handler doit
avoir obtenu une garantie durable avant de le retourner. Une combinaison
incompatible, par exemple `accepted` en mode `sync`, retourne
`500 response_mode_error`.

Pour configurer un callback depuis la CLI :

```bash
arclith-cli add-adapter \
  --capability channel \
  --adapter webhook \
  --adapter-param response_mode=callback \
  --adapter-param callback_url=https://hooks.example.test/arclith \
  --adapter-param callback_allowed_host=hooks.example.test \
  --yes
```

`Arclith.channel_sender("webhook")` construit un `WebhookCallbackSender`
uniquement lorsque ce mode est complètement configuré. Le même sender peut être
injecté dans un worker durable.

## Idempotence Et Échecs Sortants

Le store réserve atomiquement `("webhook", event_id)` avant la résolution
d'identité et le handler. Un doublon retourne `200` avec `status: duplicate`
sans réexécuter l'application.

Une erreur de résolution ou de handler libère le claim. Après la réussite du
handler, le claim est conservé même si le callback sortant échoue : rejouer le
handler pourrait dupliquer ses effets métier. Un callback critique doit donc
être écrit dans un outbox ou une file durable par le handler, puis livré et
retenté indépendamment. Un retry identique de l'émetteur ne rejouera pas le
callback perdu.

Le fake `MemoryChannel` fournit un claim atomique dans un seul processus, mais
perd son état au redémarrage et ne coordonne pas plusieurs replicas.

## Statuts HTTP

Le router déclare explicitement ses réponses dans OpenAPI :

| HTTP | Code JSON | Cause |
|---:|---|---|
| `200` | — | traitement terminé ou doublon |
| `202` | — | prise en charge durable confirmée par le handler |
| `400` | `missing_event_id` | header d'événement absent ou vide |
| `401` | `invalid_signature` | signature absente, invalide ou périmée |
| `403` | `identity_not_resolved`, `channel_unauthorized` | identité non mappée ou refusée |
| `413` | `payload_too_large` | corps au-delà de `max_payload_bytes` |
| `415` | `unsupported_media_type` | media type non JSON |
| `422` | `invalid_payload`, `unsupported_event` | schéma ou événement non supporté |
| `429` | `callback_rate_limited` | callback limité ; `Retry-After` numérique est propagé |
| `500` | `response_mode_error` | contrat handler/mode incohérent |
| `502` | `callback_rejected` | callback HTTP non-2xx et non-429/5xx |
| `503` | `callback_unavailable` | timeout, transport ou erreur 5xx du callback |

Les réponses d'erreur utilisent des détails stables. Elles ne reprennent ni
corps fournisseur, ni URL, ni signature, ni secret.

## Sécurité

- La taille est bornée pendant la lecture du stream, puis contrôlée à nouveau
  avant parsing.
- Si HMAC est activé, le corps brut est authentifié avant le parsing JSON.
- Le timestamp signé doit rester dans `signature_tolerance_seconds` et la
  comparaison utilise `hmac.compare_digest`.
- L'URL de callback ne vient jamais du payload. Elle doit être HTTPS, sans
  credentials, query ni fragment, et son hostname doit correspondre exactement
  à `callback_allowed_host`.
- Les IP littérales privées, loopback ou non globales et `localhost` sont
  refusées. Les redirects HTTP ne sont jamais suivies.
- La validation applicative ne remplace pas une politique egress : en
  production, contrôler également DNS, réseau sortant et résolution privée pour
  réduire les risques de rebinding ou de compromission de configuration.
- Les pièces jointes ne sont pas téléchargées par l'adapter.
- `sender_id`, tenant et workspace restent des affirmations externes jusqu'au
  mapping explicite du resolver.

## Production

Avant exposition publique :

1. activer HMAC avec un secret distinct par intégration et le faire tourner via
   la capability `secrets` ;
2. utiliser un `ChannelEventStore` atomique partagé et dimensionner son TTL ;
3. définir une `metadata_allowlist` minimale ;
4. injecter un resolver d'identité tenant-aware ;
5. préférer `accepted` avec file/outbox durable pour les traitements longs ;
6. borner timeout, retries et egress du callback ;
7. journaliser uniquement event ID, statut, latence et corrélation technique.

## Validation

```bash
uv run pytest -q \
  tests/units/adapters/bidirectional/webhook \
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
| `401 invalid_signature` | timestamp hors fenêtre ou corps modifié après signature | signer les octets transmis avec le même timestamp |
| `400 missing_event_id` | header configuré absent | envoyer un ID stable, identique sur les retries |
| `403 identity_not_resolved` | identité externe inconnue | créer le mapping sans utiliser directement `sender_id` comme user métier |
| `duplicate` | le couple provider/event ID est déjà claim | ne pas générer un nouvel ID pour le même événement ; inspecter le store |
| `500 response_mode_error` | le handler n'honore pas le mode | aligner `completed`/`accepted` et la garantie durable |
| `502` ou `503` callback | endpoint rejeté, indisponible ou expiré | consulter la télémétrie technique et utiliser une reprise outbound durable |

## Projet

Dans un service consommateur, garder le handler dans `application/`, le
resolver et le store dans les ports/adapters appropriés, et inclure le router
depuis le bootstrap FastAPI. Ne placer aucune logique métier, URL de callback
issue de l'utilisateur ou appel HTTP dans `domain/`.
