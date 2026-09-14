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
  Une entité existante doit fournir explicitement un enum ou un `Literal` protégé ;
  la CLI ne patche pas son fichier.
- La persistance dépend d'un port outbound spécialisé `compare_and_swap`. Son
  contrat exige une comparaison atomique de version ; une lecture suivie d'un
  update inconditionnel n'est pas présentée comme sûre.
- Le manifeste paramétré passe en version 2 et embarque `parameters`, le digest
  du template et le digest des paramètres. Les manifests V1 restent strictement
  lisibles et rejouables sans conversion.
- La recette stocke la configuration résolue, jamais le chemin de `--spec`.

## Validation

- `uv run --project cli python -m pytest cli/tests -q` : 562 tests passés ;
- tests générés dans le smoke test : 17 tests domaine/application passés ;
- `make precommit` : Ruff, mypy (232 fichiers) et Bandit passés ;
- `make coverage` : 2 472 tests passés, 5 ignorés et 91,34 % sur 9 264
  statements et 2 142 branches ;
- `make docs` : build MkDocs strict passé ;
- `uv build cli` : sdist et wheel `arclith-cli` 0.27.0 construits ;
- installation isolée sans cache du wheel, génération et compilation d'un projet
  frais contre `arclith` 0.30.0, puis transition `draft -> submitted` vérifiée.
