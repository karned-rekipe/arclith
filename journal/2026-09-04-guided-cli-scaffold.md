# Scaffold CLI Guidé

## Contexte

Les commandes `add-entity` et `add-usecase` créaient des fichiers presque
vides. Elles indiquaient le bon emplacement hexagonal, mais ne guidaient ni le
choix d'une entité principale, ni la séparation entre DTO Pydantic, port inbound
et orchestration applicative.

## Décisions

- conserver `add_entity_cmd()` et `add_usecase_cmd()` non interactifs pour les
  appels Python et le replay ;
- placer le wizard uniquement dans la couche CLI Typer ;
- réutiliser le scanner AST des entités pour `--entity` et les choix du wizard ;
- rendre `--entity`, `--new-entity` et `--no-entity` explicites et mutuellement
  exclusifs ;
- garder l'absence d'entité comme comportement backward-compatible de
  `add_usecase_cmd()` et des anciennes recettes ;
- générer des squelettes courts avec `Command`, `Query` ou `Result` Pydantic,
  sans logique métier inventée ni import de framework entrant ;
- ne pas importer `Field` tant que son exemple reste commenté ;
- enregistrer le mode de liaison dans `arclith.recipe.yaml` pour un replay
  déterministe.

## Impact

Un use case lié reçoit un `Repository[Entity]` explicite et retourne l'entité.
Un use case transverse reçoit un `Command`, retourne un `Result` et n'injecte
aucun repository par défaut. Les layouts canonique `src/<package>` et legacy
root restent pris en charge.

Aucune dépendance, aucun port Arclith partagé, aucun adapter, aucune
configuration persistante et aucune API runtime ne changent.

## Documentation

Le README CLI, le quickstart, les étapes Todo `add-entity` et `add-usecase`,
l'index des capabilities et la navigation Pages renvoient vers le nouveau deep
dive `docs/deep-dives/cli-scaffold.md`. Celui-ci couvre création, lecture,
mutation, use case transverse, port outbound métier et tests unitaires.

## Validation

- tests ciblés scaffold, recettes et E2E : 52 passés ;
- suite CLI complète : 173 passés et 1 ignoré ;
- `make quality` : Ruff, Bandit, complexité et mypy passés, 2 171 tests
  passés, 5 intégrations externes ignorées et 91,19 % de couverture ;
- `make precommit` : passé ;
- `make docs` : build MkDocs strict passé ;
- lockfiles racine et CLI : valides avec `uv lock --check` ;
- smoke test consommateur : fichiers liés et transverses compilés et validés
  par Ruff.
