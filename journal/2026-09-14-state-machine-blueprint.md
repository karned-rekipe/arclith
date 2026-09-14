# Blueprint state-machine paramétré

## Contexte

L'issue #223 est la phase 2 de l'epic #221, après le blueprint append-only livré
par #222. Elle introduit le premier blueprint dont les opérations viennent d'une
spécification métier plutôt que d'un catalogue statique.

## Décisions

- La spec V1 est chargée et validée dans un module dédié, puis convertie en
  paramètres canoniques indépendants de son chemin local.
- Les états, sources et transitions sont triés pour rendre génération et digest
  insensibles à l'ordre accidentel des listes YAML.
- Un état inaccessible est refusé. La V1 ne génère pas de code mort assorti d'un
  simple warning.
- Chaque transition devient une méthode de domaine, un port inbound et un use
  case nommés. Aucun dispatcher dynamique par chaîne n'est introduit.
- Le champ d'état créé avec l'entité est typé, validé à l'affectation et frozen.
  `model_copy` rejette aussi ce champ ; le service passe par une copie privée
  dédiée. Une entité existante doit fournir explicitement un enum vérifiable ou
  un `Literal` avec les mêmes protections ; la CLI ne patche pas son fichier.
- L'enum de matrice générée utilise le module dédié `<entité>_lifecycle_state.py`,
  afin de préserver sans collision une enum métier existante importée depuis le
  chemin conventionnel `<entité>_state.py`.
- Les annotations `Literal` et les bases `Enum` sont résolues jusqu'à leur origine
  `typing`/stdlib, y compris via alias ; les homonymes locaux et helpers de copie
  asynchrones sont refusés, comme `use_enum_values=True` pour un champ enum. Une
  seule affectation effective de `model_config` est admise ; les helpers doivent
  garder leurs signatures d’instance sans décorateur. Les defaults enum
  doivent être des membres typés. Les tests générés dérivent la valeur de
  l'annotation réelle et en vérifient le type. Les erreurs not-found incluent
  l'UUID demandé et les conflits exposent versions observée/attendue.
- La persistance dépend d'un port outbound spécialisé `compare_and_swap`. Son
  contrat exige une comparaison atomique de version ; une lecture suivie d'un
  update inconditionnel n'est pas présentée comme sûre.
- Le manifeste paramétré passe en version 2 et embarque `parameters`, le digest
  du template et le digest des paramètres. Les manifests V1 restent strictement
  lisibles et rejouables sans conversion.
- La recette stocke la configuration résolue, jamais le chemin de `--spec`, et
  exige ses deux digests lors du préflight global, avant toute écriture de replay.
  Les paramètres absents ou mal formés sont normalisés en `RecipeError`.
  Le digest du template couvre le source complet des renderers et versionne aussi
  le contrat de validation des entités existantes, sans modifier les anciens
  digests CRUD/append-only.

## Validation

- `uv run --project cli python -m pytest cli/tests -q` : 600 tests passés ;
- smoke test du projet généré : 19 tests passés ;
- `make precommit` : Ruff, mypy (232 fichiers) et Bandit passés ;
- `make coverage` : 2 480 tests passés, 5 ignorés et 91,34 % sur 9 264
  statements et 2 142 branches ;
- `make docs` : build MkDocs strict passé ;
- `uv build cli` : sdist et wheel `arclith-cli` 0.27.0 construits ;
- installation isolée sans cache du wheel, génération et compilation d'un projet
  frais contre `arclith` 0.30.0, puis refus de la copie générique et transition
  `draft -> submitted` vérifiés.
