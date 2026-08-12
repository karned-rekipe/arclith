# Captures Et Vidéos

Cette page définit le format attendu pour les supports de formation.

## Objectif

Chaque média doit aider à valider une action concrète: commande exécutée,
écran attendu, résultat visible ou chemin de navigation.

Un média ne remplace pas le texte. Il confirme visuellement une étape déjà
expliquée.

## Captures

Utiliser une capture quand l'apprenant doit reconnaître un état:

| Cas | Capture attendue |
|---|---|
| CLI | commande et sortie utile |
| API | Swagger, healthcheck ou réponse HTTP |
| MCP | tool visible dans le client |
| Agent | graphe ou trace d'exécution |
| Observabilité | trace, métrique ou log corrélé |
| Docker | container sain ou logs de démarrage |

## Vidéos

Une vidéo doit rester courte et centrée sur un seul objectif.

| Type | Durée cible | Contenu |
|---|---:|---|
| quickstart | 2 à 5 min | exécuter et valider |
| tutoriel | 5 à 12 min | construire une étape |
| deep dive | 8 à 15 min | expliquer un mécanisme |
| correction | 2 à 6 min | diagnostiquer une erreur |

## Convention De Nommage

Stocker les médias près de la page qui les utilise.

```text
docs/tutorials/todo-list/assets/04-api.svg
docs/tutorials/todo-list/assets/04-swagger.png
docs/tutorials/todo-list/assets/04-api.mp4
```

Préférer un nom qui commence par le numéro de l'étape quand la page fait partie
d'un parcours.

## Bloc Standard

```md
!!! note "Média à produire"
    Capture attendue : état précis à montrer.
    Vidéo attendue : objectif, durée cible et scénario.
```

Quand le média existe, remplacer la note par un lien ou une image:

```md
![Swagger UI](assets/04-swagger.png)
```

## Qualité Minimale

- terminal lisible;
- zoom suffisant sur le contenu utile;
- pas de secret visible;
- pas de fenêtre personnelle non liée au tutoriel;
- commandes exécutées dans l'ordre de la page;
- résultat final visible.

## Validation

Avant de publier une page avec média:

```bash
uv run --frozen --group docs mkdocs build --strict
```

Puis ouvrir la page localement et vérifier que l'image ou la vidéo se charge.

## Suite

Revenir au [format d'une page](page-format.md).
