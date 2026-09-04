# Adapter Channel Webhook

## Contexte

L'issue #170 livre le premier canal HTTP réel au-dessus du contrat
provider-neutral de #169. L'objectif est de raccorder rapidement une intégration
custom sans déplacer FastAPI, HMAC ou `httpx` dans le domaine.

## Décisions

- signer `"<timestamp>.<corps-brut>"` avec HMAC-SHA256 et comparer en temps
  constant dans une fenêtre configurable ;
- lire le corps HTTP avec une limite de taille avant parsing, puis utiliser un
  modèle JSON strict ;
- extraire l'event ID d'un header serveur et déléguer le claim atomique au
  `ChannelDispatcher` ;
- limiter les métadonnées normalisées à une allowlist explicite ;
- faire de `sync`, `accepted` et `callback` des contrats vérifiés avec le
  résultat du handler, sans tâche FastAPI locale prétendument durable ;
- configurer l'URL de callback exclusivement côté serveur, imposer HTTPS et un
  hostname exact, refuser credentials, query, fragment, redirects et IP
  littérales non globales ;
- conserver le claim après une réussite métier même si le callback échoue, et
  documenter l'outbox comme mécanisme de reprise outbound ;
- exposer `httpx` seulement via l'extra `channel` et garder le parsing HTTP hors
  du domaine, avec un contrôle fail-fast au montage du sender callback ;
- injecter le secret via la capability `secrets`, sans valeur claire dans le
  template CLI.

## Impact

Les services peuvent inclure un router FastAPI réutilisable, choisir un mode de
réponse et fournir leurs propres handler, resolver d'identité et store
d'événements. Le fake mémoire reste utile au POC, mais un endpoint multi-replica
nécessite un store atomique partagé.

## Documentation

`docs/capabilities/channel-webhook.md` contient le wiring, un exemple curl signé,
le payload, les statuts HTTP, la sécurité callback et les limites de
production. La page commune distingue désormais explicitement `channel` du
chat applicatif et rend le webhook découvrable depuis le catalogue et le
quickstart.

## Validation

- `make quality` : Ruff, Bandit, complexité et mypy passent ; 2 030 tests
  passent, 5 intégrations sont ignorées et la couverture atteint 91,08 % ;
- `make precommit` : passé sur l'état final ;
- `cd cli && uv run --frozen pytest -q` : 154 tests passent et 1 est ignoré ;
- Ruff CLI, les deux lockfiles et `make docs` strict passent ;
- les tests dédiés couvrent parsing, HMAC, fraîcheur, normalisation, modes,
  callback, taille streamée, statuts FastAPI, catalogue, template, secret et
  extra.
