# Contrat Channel Provider-Neutral

## Contexte

L'issue #169 prépare des canaux conversationnels bidirectionnels sans lier les
services Arclith à un fournisseur. Le premier incrément doit rendre le contrat
testable et découvrable avant les adapters webhook (#170) et Slack (#171).
Telegram, Email et Teams restent au backlog.

## Décisions

- séparer l'identité externe de l'identité utilisateur/tenant résolue ;
- réserver atomiquement chaque couple `(provider, event_id)` avant le handler ;
- libérer la réservation après une erreur de résolution ou de handler, mais la
  conserver après un traitement métier réussi pour ne pas rejouer ses effets ;
- garder le contrat indépendant du transport et traduire les accusés HTTP dans
  les adapters fournisseurs ;
- accepter uniquement des métadonnées JSON, ensuite réduites par chaque adapter
  à une liste blanche documentée ;
- partager la validation des nombres JSON finis avec le contrat vector-store ;
- représenter les pièces jointes par une URL HTTP(S) sans credentials ou une
  clé `storage` relative, sans octets ni chemin absolu ;
- fournir un fake mémoire mono-processus et un registry de senders extensible ;
- reconnaître `adapters/bidirectional` dans le layout, le chargeur et le
  catalogue CLI.

## Impact

Le package principal gagne des modèles, ports, erreurs et un dispatcher sans
nouvelle dépendance. Les services peuvent implémenter leur mapping d'identité et
leur store atomique sans modifier le domaine. Le fake mémoire est réservé aux
tests et POC ; il n'apporte ni durabilité ni coordination multi-replicas.

## Documentation

La page `docs/capabilities/channel.md` décrit le contrat, les garanties et les
limites de production. `docs/quickstarts/channel.md` fournit un flux exécutable
et les deux pages sont reliées depuis les index et la navigation MkDocs.

## Validation

- `make precommit` : Ruff, mypy et Bandit passent ;
- `make coverage` : 1 941 tests passent, 5 intégrations sont ignorées et la
  couverture atteint 90,94 % ;
- `cd cli && uv run --frozen pytest -q` : 152 tests passent et 1 est ignoré ;
- lint CLI, `make docs` strict et vérification des deux lockfiles passent ;
- le quickstart mémoire et la sortie JSON du catalogue ont été exécutés.
