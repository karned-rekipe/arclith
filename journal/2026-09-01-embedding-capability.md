# Capability embedding provider-neutral

## Contexte

La roadmap CLI distinguait déjà les LLM, le stockage de fichiers et les
repositories, mais ne fournissait pas de contrat commun pour calculer des
embeddings texte. Les futurs adapters OpenAI-compatible et OpenAI avaient besoin
d'un socle qui ne couple ni le domaine à un SDK, ni le calcul à la persistance.

## Décision

- ajouter `EmbeddingPort` et des modèles Pydantic stricts qui valident les
  entrées, l'ordre, le modèle et la dimension des résultats ;
- exposer des erreurs provider-neutral sans données sensibles ;
- assembler les adapters avec `EmbeddingRegistry`, `build_embedding()` et
  `Arclith.embedding()` ;
- fournir `deterministic`, un adapter sans dépendance, stable entre processus et
  normalisable, réservé aux tests et smokes ;
- charger la configuration depuis
  `config/adapters/outbound/embedding.yaml`, sans sélecteur global ;
- déclarer la capability dans le catalogue CLI et documenter sa frontière avec
  `llm`, `vector-store`, `repository` et `storage`.

## Impact

Un service peut désormais tester localement la partie embedding d'un pipeline
RAG sans provider externe. L'index vectoriel demeure une projection dérivée :
la source reste dans le repository ou le storage du service consommateur.

Les adapters OpenAI-compatible, OpenAI et les vector-stores pourront réutiliser
le contrat commun et vérifier explicitement la compatibilité des dimensions.

## Validation

- `make quality` : 1 683 tests passés, 5 ignorés, couverture 91 % ;
- `make precommit` : lint, mypy et Bandit passés ;
- tests CLI : 140 passés, 1 ignoré ;
- `make docs` : build MkDocs strict passé.
