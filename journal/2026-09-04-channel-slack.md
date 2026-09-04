# Adapter Channel Slack

## Contexte

L'issue #171 complète la trajectoire active #169 après le socle provider-neutral
et l'adapter webhook. Le besoin est de raccorder Slack Events API sans SDK dans
le domaine, tout en respectant le délai d'acquittement et les retries du
fournisseur.

## Décisions

- limiter la v1 aux Request URLs HTTP, sans Socket Mode, slash commands, block
  actions ni installation OAuth automatisée ;
- vérifier `v0:<timestamp>:<corps-brut>` avec HMAC-SHA256, une fenêtre de cinq
  minutes et une comparaison en temps constant avant tout parsing ;
- traiter `url_verification` sans dispatch et retourner le challenge en JSON ;
- normaliser uniquement `message`, `app_mention` et `file_share`, puis ignorer
  les bots, apps, éditions, suppressions et types inconnus avec un `200` ;
- utiliser `event_id` comme claim atomique et conserver les headers de retry
  uniquement dans une allowlist de métadonnées ;
- mapper `team_id`, `enterprise_id`, `channel`, `user`, `thread_ts` et `ts` vers
  les coordonnées provider-neutral, sans les promouvoir en identité métier ;
- représenter les fichiers Slack par métadonnées et URL privée HTTPS, sans
  téléchargement ni octets dans l'adapter ;
- envoyer les réponses texte vers l'URL fixe `chat.postMessage`, avec bearer
  token en header, redirects désactivées, timeout et mapping stable des erreurs ;
- conserver `thread_id` comme `thread_ts` et `message_id` comme `client_msg_id` ;
- n'émettre `accepted` que lorsque le handler a déjà pris le travail en charge
  durablement, sans créer de tâche locale trompeuse ;
- garder le claim après une réussite métier même si l'envoi Slack échoue et
  documenter une reprise outbound par outbox ;
- fournir les secrets via `ARCLITH_SLACK_SIGNING_SECRET` et
  `ARCLITH_SLACK_BOT_TOKEN`, tous deux redacted par les settings ;
- exposer le sender via la registry commune et réutiliser l'extra `channel`
  pour `httpx`.

## Impact

Les services peuvent inclure un router FastAPI Slack et brancher leurs propres
handler, resolver d'identité et store d'événements. La factory construit aussi
un sender autonome pour un worker durable. Aucun modèle ou port du domaine n'a
été spécialisé pour Slack.

## Documentation

`docs/capabilities/channel-slack.md` documente le bootstrap, le challenge local,
les scopes, les événements, la normalisation, les secrets, les statuts HTTP,
l'acquittement sous trois secondes et les limites de production. Le catalogue,
la page commune, le quickstart et la navigation rendent l'adapter découvrable.

## Validation

- fixtures provider pour challenge, message, mention, fichier et bot ;
- tests adapter pour signature, allowlists, identité, thread, retry,
  déduplication et événements ignorés ;
- tests sender pour succès, auth, rate limit, indisponibilité, erreurs stables
  et absence de fuite du token ;
- tests FastAPI pour OpenAPI, challenge, statuts, taille streamée et
  `Retry-After` ;
- tests settings, factory, chargement scoped, catalogue et génération CLI ;
- `make quality` : Ruff, Bandit, complexité et mypy passent ; 2 115 tests
  passent, 5 intégrations sont ignorées et la couverture atteint 91,21 % ;
- `cd cli && uv run --frozen pytest -q` : 155 tests passent et 1 est ignoré ;
- Ruff CLI, les deux lockfiles et le build MkDocs strict passent ;
- `make precommit` est exécuté sur l'état final avant commit.
