# Blueprint synchronization — issue #225

## Contexte

- EPIC #221 relue : #224 est fermée et livrée par PR #243 ; #225 est la phase
  suivante avant workflow #226. La fin du texte historique de l'EPIC mentionne
  encore #224 comme prochaine, mais sa checklist et le code fusionné font foi.
- `git fetch --prune` / `git pull --ff-only` : main à jour sur `8f075d9`.
- Branche `codex/issue-225-synchronization-blueprint` ; issue ajoutée au board
  Arclith #5, Sprint 7, In Progress avant l'implémentation.
- Répertoire utilisateur non suivi `catalog-servicea/` préservé.

## Décisions

- Domaine provider-neutral, ports source/mapper/cible/checkpoint ; moteur de
  pages implémenté et testé avant la génération CLI. `apply` cible est une
  opération atomique de comparaison/application ; pas de read-then-write CRUD.
- Réutilisation de JobRequest/JobRecord/JobStatus/JobHandler/JobService. Ajout
  compatible de compteurs completed/total à JobProgress et de JobContext.job_id
  (implémenté par le contexte mémoire). Aucun nouveau modèle de statut sync.
- Checkpoint séparé : curseur incrémental, version source, CAS, dernier succès
  UTC et métriques. Rapport de tentative séparé, adressé par JobId et conservé
  indépendamment du TTL du JobRecord ; erreurs fixes sans payload ni exception.
- Le curseur de pagination et le watermark terminal sont distincts :
  next_cursor=None termine la pagination ; checkpoint_cursor permet le prochain
  pull. Aucun checkpoint n'avance sur une page incomplète.
- Full reprend depuis le début après échec/annulation, conserve le watermark
  incrémental et borne les clés vues à 10 000 par défaut, 100 000 maximum.
  La désactivation atomique des absents est postérieure à toutes les pages
  validées. Un skip explicite reste une clé vue. Un full vide réussi peut
  désactiver tout le périmètre : l'adapter doit garantir une source exhaustive.
- Exclusivité par périmètre ; stores mémoire non durables, une boucle asyncio.
  Aucun recovery/lease distribué implicite. Les adapters durables doivent
  assurer le fencing des workers et l'idempotence de tous les effets cible.
- Chaque tentative décrit ses propres compteurs. Le retry Job conserve son ID
  avec budget explicite ; max_attempts=1 reste le défaut. Annulation entre pages.
- Aucun changement du factory Repository : ces ports ne sont pas des CRUD.

## CLI et compatibilité

- Blueprint synchronization entity-scoped, spec V1, manifeste V2 et recette V1
  existants ; aucune évolution de format nécessaire.
- Modèles source/patch limités initialement à la clé externe, mapper métier
  NotImplementedError, quatre ports/use cases et trois ports outbound spécialisés.
  Les tests fournissent leurs propres fakes. L'entité existante n'est pas modifiée.
- Dépendance Job/Synchronization vérifiée avant génération/replay. Pas de
  transport, adapter, broker ni scheduler installé implicitement.
- Empreintes de recettes Job capturées avant les changements CLI : 68 fichiers
  des deux cibles comparés octet pour octet. La fixture state-machine existante
  reste inchangée ; seul le hash exact audité du catalogue étendu est ajouté à
  la migration de source, sans désactiver la détection de dérive ultérieure.

## Validation

- 57 tests ciblés synchronization ; 187 tests CLI ciblés au jalon intermédiaire.
- Suite framework : 2713 passés, 5 ignorés ; couverture 91,90 %.
- Suite CLI complète : 820 passés, un warning Pydantic préexistant sur une
  fixture CRUD utilisant Final.
- make quality (lint, types, sécurité, complexité, couverture) : réussi.
- Build MkDocs strict et exemple Python complet de la page : réussis.
- Page locale ouverte dans le navigateur : navigation, contenu et exemples
  présents ; séquence présentée en étapes compatibles avec le rendu MkDocs.
- Wheels et sdists framework/CLI construites, installées ensemble dans un
  Python 3.13 neuf, sans source éditable ni extra de transport.
- Projet consommateur frais : compilation, 6 tests générés et lint réussis.
  Use cases générés : 20 soumissions concurrentes dédupliquées, échec partiel,
  curseur préservé, retry depuis la bonne page, absence de double effet,
  full avec désactivation et conservation du watermark incrémental vérifiés.
- Exemple Python Pages également exécuté depuis les wheels isolées.
- Nouveau CLI installé avec l'ancien Arclith 0.31.0 depuis l'index public :
  génération synchronization refusée avec explication, aucun fichier modifié.
- Revue finale : clés dupliquées refusées avant application dans une page et
  sur tout un full, empêchant les mises à jour contradictoires au retry ;
  compteur/position de page avancé uniquement après confirmation du checkpoint.

## Livraison

Documentation Pages dédiée, index, capabilities, navigation, quickstart, recettes,
README CLI, page Job et changelog Unreleased actualisés. Les numéros des wheels
de test sont ceux du checkout ; aucun paquet ni tag de release n'est publié.
La PR doit cibler main et fermer #225 ; les checks/review threads seront relus
avant passage In review. La publication Pages intervient après fusion.
