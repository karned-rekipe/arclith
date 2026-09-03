# Routing Repository Par Entité

## Contexte

La configuration Arclith sélectionnait un unique adapter repository global.
Cette convention reste adaptée aux services mono-store, mais empêchait un même
bounded context de persister explicitement des aggregates distincts dans des
stores différents sans écrire son propre mécanisme de sélection.

## Décision

- ajouter `adapters.repository_bindings`, indexé uniquement par le chemin Python
  complet de la classe d'entité ;
- conserver `adapters.repository` comme fallback backward-compatible ;
- centraliser la résolution dans `AdaptersSettings.repository_adapter_for()` ;
- faire consommer cette résolution par `RepositoryRegistry`, y compris pour les
  registries applicatifs ;
- valider la section de configuration de chaque adapter intégré référencé ;
- échouer à la construction lorsqu'un binding sélectionne un adapter absent du
  registry, sans fallback implicite ;
- activer le pipeline tenant si au moins un adapter réellement sélectionné est
  multitenant ;
- garder `Repository[T]`, le domaine et les use cases inchangés.

## Impact

`Arclith.repository(Entity)` peut désormais assembler MongoDB, MariaDB, DuckDB,
PostgreSQL, memory ou des adapters custom dans une même application. Les
containers générés journalisent l'adapter effectivement sélectionné pour leur
entité. Aucun nouveau port SQL/NoSQL, aucune dépendance et aucune transaction
cross-store ne sont introduits.

## Documentation

`docs/capabilities/repository.md` présente la configuration complète
MongoDB/MariaDB, le fallback, l'injection des ports, la validation, les limites
transactionnelles, les frontières de bounded context et le comportement
multitenant. L'index `docs/capabilities.md` rend ce routing découvrable. Un ADR
séparé n'est pas nécessaire : ce choix étend le registry configurable déjà
défini par ADR-010 sans modifier les frontières hexagonales.

## Validation

- tests ciblés configuration/factory/bootstrap repository : 143 passés, 4
  ignorés car extras optionnels absents lors de ce run ciblé ;
- test CLI du container généré : 1 passé ;
- `make quality` : Ruff, Bandit, complexité et mypy passés, 1 850 tests passés,
  5 intégrations externes ignorées et 90,65 % de couverture ;
- `make precommit` : passé ;
- suite CLI complète : 150 passés, 1 ignoré ;
- lockfiles racine et CLI : valides avec `uv lock --check` ;
- `make docs` : build MkDocs strict passée.
