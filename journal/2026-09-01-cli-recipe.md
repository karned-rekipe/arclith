# CLI recipe : historique et replay des mutations

## Contexte

L'issue #175 demande une trace lisible, versionnée et rejouable des décisions
prises via `arclith-cli`, distincte de Git et de `export-config`.

## Changements

- ajout du schéma YAML `version: 1` et des modèles `Recipe`, `RecipeStep`,
  `RecipeSecretRef` et `RecipeResult` ;
- séparation SRP entre modèles/validation YAML, enregistrement/replay, handlers
  Typer et scaffolding du projet `new` ;
- écriture atomique de `arclith.recipe.yaml` après chaque mutation réussie ;
- capture des paramètres résolus et des fichiers créés ou mis à jour avec des
  chemins relatifs ;
- redaction des secrets par métadonnées du catalogue et heuristique défensive ;
- ajout des commandes `history` et `replay`, du dry-run, des bornes de steps et
  du mode strict ;
- alignement du plan de dry-run sur les étapes réellement rejouables et
  signalement explicite des commandes ignorées hors mode strict ;
- empreinte des liens symboliques fondée sur leur cible pour détecter leurs
  mises à jour ;
- replay direct des fonctions Python existantes, sans shell et sans double
  enregistrement ;
- documentation Pages, README CLI et quickstart mis à jour.

## Validation prévue

- tests ciblés du module recipe et des commandes mutantes ;
- suite CLI complète ;
- `make precommit`, `make coverage` et `make docs` à la racine ;
- vérification des lockfiles racine et CLI.

## Compatibilité et risques

Le runtime `arclith` et le catalogue de capabilities ne changent pas. La
recette est une utilité CLI KISS. Le schéma inconnu est refusé explicitement et
les chemins absolus externes ne sont jamais persistés tels quels.
