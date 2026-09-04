# Mapping relationnel structuré optionnel

## Contexte

L'issue #177 demande de conserver `Repository[T]` comme port CRUD commun tout
en permettant à une application de matérialiser certaines entités PostgreSQL
dans des colonnes typées. Le stockage JSONB existant doit rester le défaut et
le domaine ne doit dépendre ni de SQLAlchemy ni d'un schéma physique.

## Décision

- ajouter un contrat pur Python `RelationalEntityMapper` et des déclarations
  vendor-neutral de colonnes et d'index dans l'adapter outbound relationnel ;
- résoudre les mappers par identité exacte de classe via
  `RelationalMapperRegistry`, fourni explicitement par l'assemblage applicatif ;
- supporter `mapping_strategy: structured` dans PostgreSQL seulement pour cette
  première itération ; MariaDB conserve son payload JSON générique ;
- garder `generic_json` et la création de schéma activée comme valeurs par
  défaut afin de préserver le comportement PostgreSQL existant ;
- permettre `auto_create_schema: false` afin qu'un déploiement de production
  confie la création et l'évolution du schéma à ses migrations applicatives ;
- exiger les colonnes techniques nécessaires au contrat `Repository[T]` et
  valider les identifiants, collisions et références d'index avant accès à la
  base.

## Conséquences

Le code métier et les use cases continuent à dépendre de `Repository[T]`.
L'application garde la responsabilité de la conversion complète de l'entité,
des ports de requêtes métier, des migrations et des contraintes cross-store.
Arclith ne fournit ni génération automatique de mapper, ni relations, ni query
DSL, ni `ALTER TABLE` implicite.

Le catalogue CLI expose les deux options PostgreSQL dans la configuration
générée. Les facets continuent à décrire `generic_json`, qui reste la stratégie
par défaut, et documentent l'opt-in structuré.

## Validation

- tests unitaires du contrat, du registre, des validations et du round-trip ;
- construction SQLAlchemy des colonnes, contraintes et index PostgreSQL ;
- CRUD sur engine fake sans création implicite lorsque
  `auto_create_schema=false` ;
- compatibilité de `build_repository()` et `Arclith.repository()` avec et sans
  registre de mappers ;
- génération CLI et chargement de la configuration PostgreSQL ;
- `make quality`, `make precommit` et `make docs` avant livraison.
