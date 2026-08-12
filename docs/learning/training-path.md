# Parcours De Formation

Ce parcours sert d'initiation pour les nouveaux venus.

## Objectif

Comprendre Arclith en construisant progressivement un service réel.

## Progression

1. préparer l'environnement local;
2. comprendre les fondations;
3. exécuter les quickstarts;
4. construire le service Todo;
5. ajouter la baseline production;
6. lancer avec Docker;
7. lire les approfondissements selon le besoin.

Chaque bloc produit un résultat vérifiable. Ne pas avancer si la validation de
la page courante échoue.

## Parcours Court

| Étape | Page | Résultat |
|---|---|---|
| 1 | [Préparer son poste](setup.md) | CLI, Python et Docker prêts |
| 2 | [Comprendre le modèle](foundations.md) | vocabulaire commun |
| 3 | [Quickstarts essentiels](quickstarts.md) | API, MCP, bus et agent lancés |
| 4 | [Projet Todo](../tutorials/todo-list/index.md) | service complet |
| 5 | [Validation finale](validation.md) | critères de passage validés |

Le format des supports vidéo et captures est décrit dans
[Captures et vidéos](media.md).

## Parcours Production

Après le parcours court:

1. appliquer la [baseline production](../production/baseline.md);
2. lire [Auth](../production/auth.md);
3. lire [Cache](../production/cache.md);
4. lire [Secrets et Vault](../production/secrets.md);
5. lire [Observabilité](../production/observability.md);
6. lancer le [tutoriel Docker](../runtime-docker.md);
7. lire [Kubernetes](../runtime-docker/kubernetes.md).

## Règle De Passage

Ne pas passer à l'étape suivante tant que la validation de la page courante ne passe pas.

## Médias À Produire

!!! note "Média à produire"
    Vidéo courte : dérouler le parcours complet jusqu'à l'API locale.
    Capture : navigation du site avec les sections Quickstarts, Foundations, Formation et Production.

## Suite

Commencer par [Préparer son poste](setup.md).
