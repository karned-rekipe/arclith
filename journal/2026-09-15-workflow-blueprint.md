# Blueprint workflow — issue #226

## Préparation

- PR #244 relue : huit checks verts, quatre conversations Code Quality résolues,
  aucun nouveau retour Copilot. Fusion squash autorisée par l'utilisateur :
  `750fab838998b3b0c147f9e22626ac42b6092cea` ; #225 fermée et classée Done.
- Publication Pages #225 réussie, page Synchronization accessible en HTTP 200.
- `git fetch --prune` puis `git pull --ff-only` avant la nouvelle branche
  `codex/issue-226-workflow-blueprint` ; répertoire `catalog-servicea/` préservé.
- #226 ajoutée au board Arclith #5, Sprint 7, In Progress avant les changements.

## Contrats retenus

- Séquence de 1 à 100 étapes typées injectées, contexte homogène et résultat
  distinct projet-owned ; projection pure explicite après toutes les étapes.
- Réutilisation de JobProgress, CancellationToken et de la sérialisation Job
  (JSON natif, 64 KiB, 32 niveaux, exact type et refus des champs secrets masqués).
  Vocabulaire Workflow distinct du statut métier et de Job ; aucun héritage forcé.
- Définition/version complète et digest définition + schémas Pydantic enregistrés.
  La sémantique du code métier exige un bump explicite de définition_version.
- Transition fermée, claim exclusif, contrôle du propriétaire et CAS ; contexte,
  succès d'étape et checkpoint atomiques. Les erreurs de persistance remontent
  comme issue incertaine, sans les convertir en échec métier.
- Reprise uniquement failed/running sans propriétaire actif, en relisant le store.
  Les étapes confirmées sont sautées. Les tentatives sont consommées avant appel ;
  max_attempts=1 par défaut, maximum 100, aucun retry automatique. Clé stable
  WorkflowId/digest/étape pour dédupliquer les effets non confirmés.
- Annulation coopérative entre étapes et avant completion. L'étape en cours peut
  finir ; aucune reprise d'une instance cancelled. Une étape non confirmée peut
  conserver son dernier statut running dans un workflow cancelled.
- Résultat uniquement après completion ; projection pure répétable après échec
  sans rejouer les étapes ni consommer leur budget.
- Progression par compteurs et 200 derniers événements de métadonnées maximum.
  Aucun audit durable, exactly-once, scheduler, DAG, saga ou attente humaine.
- Store mémoire borné à 1000 instances par défaut, rétention explicite ; aucun
  lease/recovery distribué. Un adapter durable doit fencer les anciens workers,
  y compris leurs effets externes, avant de reprendre un claim après crash.

## CLI, documentation et compatibilité

- Spec V1, paramètres normalisés et digest déterministe ; manifeste V3 avec cible
  standalone/entity, recette V1 inchangée. Le runtime requis est vérifié avant
  génération/replay. L'entité existante n'est jamais modifiée par le workflow.
- Cinq ports/use cases : start/get_status/cancel/resume/get_result. Étapes de
  production et projection NotImplementedError ; tests avec fakes séparés.
- Les tests générés choisissent une étape ayant un budget de retry, si disponible,
  et vérifient que les étapes confirmées ne sont pas répétées.
- Import blocks produits par le renderer normalisés sans exécutable externe ;
  aucun fichier utilisateur existant n'est reformaté.
- Empreintes des cinq blueprints précédents capturées avant modification du
  catalogue ; recette Synchronization et ses 53 fichiers comparés exactement.
  Les fixtures Job/state-machine précédentes restent inchangées. Migration du
  hash de source state-machine limitée à l'empreinte exacte auditée du catalogue.
- Pages : guide Workflow, choix use case/Job/Workflow, navigation, capabilities,
  quickstart, recettes, README CLI et changelog Unreleased actualisés.

## Validation

- Framework : 2831 tests passés, 5 ignorés, couverture 92,28 % ; make quality
  (lint, types, sécurité, complexité et couverture) réussi.
- 70 tests workflow, dont pannes avant/après checkpoint, CAS/concurrence,
  annulation, reprise, budgets, snapshots invalides et sérialisation sensible.
- CLI : 859 tests passés ; 39 tests dédiés workflow, incluant les deux cibles,
  dry-run, rollback, collisions, replay, dérive, imports et runtime incompatible.
- Build MkDocs strict ; page locale inspectée dans le navigateur et exemple
  Python exécuté dans le checkout et depuis les wheels isolées.
- Wheels et sdists construits ; environnement Python 3.13 neuf sans source
  éditable, framework chargé depuis site-packages, aucun extra de transport.
- Service généré avec les deux cibles : compilation, six tests générés et lint
  des fichiers workflow réussis. Le modèle Document minimal du scaffold conserve
  son pass préexistant (PIE790) ; il est hors du périmètre de ce contrôle de lint.
- Cinq opérations générées exercées ; vingt soumissions concurrentes dédupliquées,
  panne avant checkpoint, clé stable, absence de double effet et reprise validées.
- CLI construit avec framework public incompatible : refus clair avant écriture.

## Livraison

PR vers main avec Closes #226 ; revue des conversations GitHub et checks requis
avant passage In review. Les versions des artefacts de test restent celles du
checkout (Arclith 0.31.0 / CLI 0.28.0) : aucun paquet, tag ou release n'est publié.
