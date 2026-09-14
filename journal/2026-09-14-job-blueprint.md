# Blueprint job — issue #224

## Contexte vérifié

- EPIC #221 : append-only #222 et state-machine #223 fusionnés ; #224 est
  l'itération suivante, avant synchronization #225 et workflow #226.
- Checkout mis à jour par fast-forward de `839f36c` à `e3b9202` avant les edits
  (release Arclith 0.31.0 / CLI 0.28.0). Le répertoire utilisateur non suivi
  `catalog-servicea/` est préservé.
- Branche : `codex/issue-224-job-blueprint`.
- Issue ajoutée au board Arclith #5, Sprint 7 (14–20 septembre), In Progress.

## Décisions et réalisation

- Primitives Pydantic génériques, JobId UUIDv7, statut fermé, dates UTC,
  progression en pourcentage et enveloppes request/result/error V1.
- Transitions typées contrôlées avec version attendue : aucun save arbitraire.
  Les invariants ont été testés avant l'implémentation du runner.
- Retry explicite du même JobId, tentative incrémentée, historique minimal,
  max_attempts=1 par défaut. Annulation queued immédiate ; running coopérative.
- Store mémoire sûr entre coroutines d'une boucle asyncio, copies isolées,
  idempotence sur requête et politique canoniques, purge explicite après
  rétention terminale avec retrait des clés. Store/runner non durables.
- Runner piloté par `await run(job_id)`, sans tâche lancée implicitement.
  Les erreurs publiques ont des codes fixes. Une erreur de persistance à la
  publication du résultat remonte, sans fabriquer un échec métier certain.
- Payloads JSON natifs bornés à 64 KiB et 32 niveaux, sans objets fournisseur
  ni SecretStr/SecretBytes. Les champs masqués à la sérialisation ne sont pas
  masqués de l'empreinte ; les projets excluent leurs secrets en texte libre.
- CLI `add-blueprint job --entity …` ou `--no-entity --feature …`, spec V1,
  cinq ports/use cases typés et container injecté. Handler initial explicite
  levant NotImplementedError ; les tests injectent un fake métier.
- Manifestes V3 avec cible entity/standalone ; arguments de recette
  `target_version: 1`, enveloppe de recette V1 conservée. Formats V1/V2 lus et
  rejoués sans réécriture implicite.
- Le hash historique state-machine incluait tout le catalogue. Une migration
  limitée à une empreinte de sources auditée conserve le digest CLI 0.28.0 ;
  les fixtures enregistrées avant les edits vérifient les fichiers produits
  octet pour octet, et les tests de dérive des modules restent actifs.
- Exceptions réutilisées dans `arclith.domain.errors.job` ; pas de duplications
  d'exceptions par feature ni de branche dans le factory Repository CRUD.
- Documentation Pages : page dédiée, index blueprints/capabilities, quickstart,
  recettes, navigation MkDocs, README CLI et changelog Unreleased.

## Validation locale

- Tests moteur ciblés : **92 passés** (matrice, concurrence, annulation/retry,
  versions, champs cachés, erreurs bornées, rétention, persistance incertaine).
- Tests CLI job : **47 passés**, incluant les deux cibles et les deux politiques
  d'annulation, compilation/tests générés, dry-run, collisions/compensation,
  replay portable, dérives et compatibilité exacte state-machine.
- Suite CLI complète : **777 passés**, un warning Pydantic déjà existant sur
  une fixture CRUD utilisant Final.
- `make precommit` : lint, mypy et Bandit verts.
- `make complexity` : vert après séparation des validations JSON natives.
- `make coverage` : **2628 passés, 5 ignorés**, **91,62 %**.
- `make docs` : build MkDocs strict réussi ; page HTML servie avec HTTP 200.
  L'inspection visuelle dans le navigateur intégré n'a pas pu aboutir : timeout
  sur localhost puis refus d'accès à sa page d'erreur par la politique du
  navigateur. Aucun contournement ; validation visuelle non revendiquée.
- `uv build` et `uv build cli` : wheels et sdists construites.
- Installation des deux wheels dans un venv Python 3.13 neuf, sans sources
  éditables ni extras de transport. Le framework importé vient de site-packages.
- Projet frais avec les deux features : compilation et **8 tests passés**.
  Scénario métier typé généré : somme=6, 20 soumissions concurrentes dédupliquées,
  conflit de payload refusé et personnalisations de modèles préservées.
- Exemple Python complet de la page Job exécuté dans ce même venv : réussi.

## Publication

Cette livraison prépare une PR vers main ; aucune release ni publication PyPI
n'est effectuée. Les wheels de smoke portent les versions courantes du checkout
et servent uniquement à valider le packaging des sources de la PR. La page
documente l'installation de développement en attendant une release compatible.
Le workflow Pages existant publiera les docs après fusion sur main ; le build
local ne constitue pas une preuve de déploiement du site public.
