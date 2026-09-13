# Blueprint append-only — #222, première itération de #221

## Décisions

- Fondation #220 vérifiée fusionnée dans main (`23dc47b`). Le manifeste reste en
  version 1 ; le profil minimal et les anciennes recettes sont inchangés.
- `ImmutableRecord` est distinct d'`Entity` : UUID, temps métier obligatoire,
  timestamp UTC attribué par le store et modèle frozen.
- `AppendOnlyStore[T]` expose uniquement `append`, avec résultats appended/duplicate,
  conflit d'idempotence explicite et refus d'un UUID déjà utilisé sous une autre clé.
- Le store mémoire prend des snapshots profonds, compare une empreinte canonique
  SHA-256 et protège les appends concurrents d'une même boucle asyncio.
- La composition exige un store injecté : pas de réutilisation artificielle du
  repository CRUD, de nouvelle factory ou de copie des erreurs génériques.
- Le blueprint est opt-in via le catalogue, add-entity/new ou add-blueprint. Il
  génère les contrats, le use case, le container, les tests et les explications.

## Vérifications

Tests du modèle, du store et de la canonicalisation ; générations CLI, dry-run,
collisions de cibles/parents, replay, manifeste incompatible, modèles avec champs
métier et projets frais compilés/testés. Suites complètes framework et CLI,
precommit, complexité, couverture, documentation stricte et builds des paquets.

Les contrôles de review portent notamment sur l'absence de mutation du stockage
via des collections imbriquées, les champs masqués par des serializers, l'identité
stable des retries et la prévalidation avant écriture.

## Limites et suivi

Le store mémoire n'est pas durable, multi-processus ou distribué. Aucune query,
surface de transport, implémentation event sourcing ou batch n'est incluse.
Les versions publiées ne sont pas modifiées par cette itération : les validations
utilisent les sources et paquets construits depuis la branche.

Le board GitHub Projects Arclith #5 est fermé et aucun sprint actif Arclith n'est
confirmé. Ce blocage de pilotage est consigné dans #221/#222 ; aucun autre projet
n'est modifié arbitrairement. La phase suivante #223 reste hors de cette livraison.
