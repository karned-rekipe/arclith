# Parcours De Formation

Ce parcours sert d'initiation pour les nouveaux venus.

## Objectif

Apprendre Arclith par niveaux de lecture, du POC au projet complet.

## Progression

1. lancer un quickstart pour valider le POC;
2. lire les foundations pour préparer l'environnement et comprendre le modèle;
3. suivre une formation ciblée pour apprendre un geste précis;
4. lire la capability correspondante pour connaître le contrat complet;
5. valider les briques IA locales si le projet contient un agent;
6. réaliser un projet end to end pour assembler les briques.

Chaque bloc produit un résultat vérifiable. Ne pas avancer si la validation de
la page courante échoue.

## Parcours Court

| Étape | Page | Résultat |
|---|---|---|
| 1 | [Quickstarts essentiels](quickstarts.md) | POC API, MCP, bus ou agent validé |
| 2 | [Préparer son poste](setup.md) | CLI, Python et Docker prêts |
| 3 | [Comprendre le modèle](foundations.md) | vocabulaire commun |
| 4 | [Validation IA locale](local-ai-validation.md) | LM Studio et LangGraph testés sans LangSmith |
| 5 | [Projet Todo](../tutorials/todo-list/index.md) | service complet |
| 6 | [Validation finale](validation.md) | critères de passage validés |

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
    Capture : navigation du site avec les sections Quickstart, Foundations, Formation, Capabilities et Projets.

## Suite

Commencer par [Quickstarts essentiels](quickstarts.md).
