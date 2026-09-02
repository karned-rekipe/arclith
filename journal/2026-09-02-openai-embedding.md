# Adapter embedding OpenAI officiel

## Contexte

Le port `EmbeddingPort` disposait d'un adapter déterministe et d'un transport
OpenAI-compatible destiné aux runtimes locaux. Il manquait un adapter explicite
pour l'API OpenAI officielle, avec une politique stricte de secret et les
paramètres propres au contrat `POST /v1/embeddings`.

## Décision

- réutiliser le transport `httpx` de l'extra optionnel `arclith[embedding]`
  plutôt que d'ajouter le SDK OpenAI à l'installation minimale ;
- ajouter l'adapter `openai` dans la factory et le catalogue CLI ;
- imposer une clé résolue par `adapters.embedding.api_key`, avec le mapping
  `OPENAI_API_KEY`, avant toute requête ;
- envoyer `encoding_format: float` et omettre `dimensions` lorsqu'elle vaut
  `null` ;
- déduire alors la dimension du résultat, vérifier sa cohérence entre
  sous-batches et conserver la vérification stricte lorsqu'elle est configurée ;
- conserver l'ordre d'entrée via l'index provider et agréger les métriques de
  tokens ;
- traduire authentification, rate limit ou quota, timeout et erreurs provider
  vers les exceptions `Embedding*` sans exposer secret, texte ou payload ;
- garder un modèle placeholder dans le scaffold : le service choisit un modèle
  réellement disponible dans son projet OpenAI.

## Impact

Les projets consommateurs peuvent activer `embedding/openai` sans coupler leurs
use cases à OpenAI. La CLI génère une configuration scoped chargeable, un
mapping de secret idempotent et aucune fausse clé. Les adapters existants
conservent leurs dimensions obligatoires et leurs defaults de normalisation.

Les tests utilisent uniquement `httpx.MockTransport`; aucune clé ni requête
OpenAI réelle n'est nécessaire pour les validations automatisées.

## Validation

- `make quality` : 1 739 tests réussis, 5 ignorés, couverture 90,71 %,
  Ruff, Bandit, complexité et mypy verts sur 191 fichiers ;
- `make precommit` : Ruff, mypy et Bandit verts ;
- `uv run --frozen pytest -q` depuis `cli/` : 143 tests réussis,
  1 ignoré ;
- `make docs` : build MkDocs strict réussi ;
- tests embedding ciblés : 49 tests framework et 6 tests CLI réussis.
