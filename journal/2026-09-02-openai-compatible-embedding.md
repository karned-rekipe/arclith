# Adapter embedding OpenAI-compatible

## Contexte

Le port `EmbeddingPort` et l'adapter déterministe permettaient de valider un
pipeline local sans provider, mais aucun adapter ne pouvait encore appeler un
modèle d'embedding exposé par LM Studio, vLLM, LocalAI ou un autre runtime
compatible avec le protocole OpenAI.

## Décision

- utiliser `httpx.AsyncClient` derrière l'extra optionnel
  `arclith[embedding]`, importé uniquement à l'exécution de l'adapter ;
- appeler `POST /embeddings` relativement à une `base_url` qui contient déjà
  le préfixe API, sans accepter de credentials ni de query string dans l'URL ;
- découper les entrées selon `batch_size`, réordonner chaque réponse avec
  l'index provider et agréger les métriques d'usage ;
- vérifier le modèle et la dimension avant de construire la réponse commune ;
- traduire auth, rate limit, requête invalide, timeout et indisponibilité vers
  les exceptions `Embedding*`, avec des messages sans clé ni texte source ;
- permettre une normalisation L2 locale uniquement quand `normalize` est
  explicitement activé ;
- générer une configuration CLI idempotente et ajouter automatiquement l'extra
  `embedding` au projet consommateur.

## Impact

L'installation de base ne charge pas `httpx` via le module embedding. Les tests
utilisent `httpx.MockTransport` et n'appellent aucun serveur réel. Les services
peuvent remplacer un runtime local sans modifier leurs use cases tant que le
protocole, le modèle et la dimension restent compatibles.

Les clés d'endpoint protégé doivent être résolues hors Git. La valeur
`local-dev` du template est un placeholder non secret pour les runtimes locaux
qui exigent un header Authorization.

## Validation

- `make quality` : 1 710 tests réussis, 5 ignorés, couverture 90,63 %,
  lint, Bandit, complexité et mypy verts sur 189 fichiers ;
- `make precommit` : lint, mypy et Bandit verts ;
- `uv run --frozen pytest -q` depuis `cli/` : 141 tests réussis, 1 ignoré ;
- `make docs` : build MkDocs strict réussi.
