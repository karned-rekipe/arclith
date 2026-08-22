# Validation Finale

Cette page sert de grille de sortie pour un nouvel arrivant.

## Objectif

Valider que la personne sait utiliser Arclith pour créer, exposer, tester et
opérer un service simple.

## Critères

| Domaine | Attendu |
|---|---|
| CLI | créer un projet et ajouter une capability |
| Métier | écrire une entité et un use case sans dépendance technique |
| API | exposer un use case via FastAPI |
| MCP | exposer le même use case via un tool |
| Agent | brancher un graphe qui appelle le use case |
| IA locale | prouver LM Studio et LangGraph sans LangSmith |
| Tests | tester le domaine sans serveur externe |
| Production | expliquer auth, cache, secrets, observabilité et probes |
| Docker | builder et lancer un runtime local |

## Exercice

Créer un service minimal avec:

1. une entité;
2. un use case de création;
3. un use case de lecture;
4. une API locale;
5. un tool MCP;
6. un repository `memory`;
7. un test LM Studio ou fake LLM documenté;
8. une validation LangGraph locale par API;
9. une validation Docker locale.

## Validation Technique

```bash
uv run pytest
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:1234/v1/models
docker build -t arclith-training:local .
```

Adapter le port HTTP si le projet généré utilise une autre valeur.
Le test LM Studio peut être remplacé par un fake LLM si le poste est volontairement sans modèle local.

## Revue

La revue doit vérifier:

- pas de logique métier dans les routes ou tools;
- pas de secret versionné;
- validation d'entrée explicite;
- erreurs HTTP cohérentes;
- tests reproductibles;
- mode hors ligne explicite quand LangSmith n'est pas disponible;
- documentation de chaque capability activée.

## Média

!!! note "Média à produire"
    Capture attendue : résultat des tests, healthcheck API et build Docker.
    Vidéo attendue : soutenance courte du projet d'exercice.

## Suite

Lire les [deep dives](../deep-dives/api.md) selon le besoin du projet, et
[Validation IA locale](local-ai-validation.md) pour les projets agent.
