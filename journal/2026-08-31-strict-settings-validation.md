# Validation stricte des settings

## Contexte

La review de la refactorisation structurelle a relevé que certaines sections de `config.yaml`
ignoraient encore les clés inconnues, tandis que les settings OpenTelemetry, LangSmith et stockage
les refusaient déjà. Une faute de frappe pouvait donc produire une configuration valide mais
inefficace.

## Décision

- partager une base Pydantic interne avec `extra="forbid"` entre tous les modèles de settings ;
- conserver les options spécifiques de PostgreSQL pour les alias de champs ;
- retirer la directive de chargement `secrets` après résolution et avant la validation d'`AppConfig` ;
- vérifier les erreurs aux niveaux racine, adaptateurs et repositories imbriqués.

## Impact

Les configurations valides sont inchangées. Une clé YAML inconnue échoue désormais tôt avec une
erreur de validation explicite au lieu d'être ignorée silencieusement.

La page `docs/deep-dives/configuration.md` documente ce comportement et corrige le nom de la clé
`resolver` utilisée par `secrets.yaml`.
