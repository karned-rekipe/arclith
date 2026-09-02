# Capability vector-store : contrat commun et adapter memory

## Contexte

L'issue #147 introduit une persistance de recherche vectorielle distincte du
repository métier et du stockage de fichiers. Le premier adapter doit permettre
un usage exécutable sans service ni dépendance externe avant l'intégration de
Qdrant prévue par #148.

## Décisions

- Le domaine expose des modèles Pydantic stricts et un `VectorStorePort` limité
  aux vecteurs denses.
- Les payloads utilisent `JsonValue` afin qu'aucun objet Python arbitraire ne
  traverse le port.
- Les scores sont toujours triés du plus pertinent au moins pertinent ; la
  distance euclidienne mémoire est convertie en `1 / (1 + distance)`.
- L'adapter mémoire exige un `ensure_collection()` explicite, valide les batchs
  avant mutation et copie profondément les points stockés et retournés.
- `config/adapters/outbound/vector_store.yaml` alimente
  `adapters.vector_store`, sans sélecteur dans `adapters.yaml`.
- Le registry public permet aux applications d'ajouter un backend sans modifier
  le domaine.

## Validation prévue

- Tests des modèles, de l'adapter mémoire, de la config, de la factory et du
  scaffold CLI.
- `make quality`, `make precommit` et `make docs`.

## Impact et suites

Aucune dépendance n'est ajoutée. Le contrat et l'adapter mémoire sont inclus
dans le package principal. #148 pourra ajouter Qdrant derrière ce port et mapper
ses erreurs propres vers les exceptions communes.
