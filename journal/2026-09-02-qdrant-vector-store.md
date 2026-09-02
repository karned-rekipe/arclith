# Adapter Qdrant pour vector-store

## Contexte

La capability `vector-store` disposait du contrat provider-neutral et d'un
adapter mémoire de référence. La roadmap demande désormais une cible Qdrant
async sans transformer l'index de recherche en repository métier canonique.

## Décision

- utiliser `qdrant-client==1.19.0`, version stable vérifiée au moment de
  l'implémentation, uniquement dans les extras `qdrant` et `all` ;
- importer le SDK paresseusement pour préserver l'installation minimale ;
- limiter la v1 à une collection, un vecteur dense et des filtres exact-match
  `str`/`int`/`bool` ;
- valider les dimensions avant tout appel provider et traduire les erreurs
  HTTP/transport vers les erreurs de `VectorStorePort` ;
- réutiliser un client possédé par l'adapter en single-tenant, et fermer un
  client isolé après chaque opération multitenant afin de ne pas mettre les
  credentials tenant en cache ;
- résoudre `url`, `api_key` et `collection_name` dans le contexte `qdrant`,
  avec repli champ par champ sur la configuration de base ;
- générer le mapping `QDRANT_API_KEY` sans valeur secrète versionnée ; le
  mapping optionnel `QDRANT_URL` reste à la charge du service qui en a besoin.

## Conséquences

`Arclith.vector_store()` construit Qdrant via la registry standard et le CLI
peut scaffolder une configuration directement chargeable. Les fonctions
avancées Qdrant, la génération d'embeddings et la synchronisation d'index
restent explicites et hors scope.

## Validation

- tests unitaires sans serveur externe pour création, upsert, suppression,
  recherche, erreurs, dépendance optionnelle et multitenant ;
- tests de configuration, factory, exports et catalogue CLI ;
- `make quality`, `make precommit`, tests CLI et `make docs`.
