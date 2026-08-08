# 4. Exposer une API

Objectif: générer la configuration FastAPI avec la CLI, puis exposer `CreateTodoPort` et
`ListTodosPort` par HTTP.

![Capture interactive FastAPI](assets/04-api.svg)

## Générer l'adapter

Depuis la racine du projet:

```bash
arclith-cli add-adapter --capability api
```

Répondre aux prompts:

```text
① Type d'adapter
   1  fastapi

  Votre choix (numéro ou nom): 1

③ Paramètres fastapi
  Host FastAPI (0.0.0.0): 0.0.0.0
  Port FastAPI (8000): 8120
  Activer le reload FastAPI [y/n] (y): y

  Confirmer la génération ? [y/n] (y): y
```

La CLI crée:

```text
config/adapters/inbound/fastapi.yaml
```

## Sous-étapes

1. [Configurer FastAPI et les schémas HTTP](04-api-config-schemas.md)
2. [Écrire les handlers HTTP](04-api-handlers.md)
3. [Déclarer le router et brancher FastAPI](04-api-router-main.md)
4. [Tester l'API](04-api-tests.md)

## Rôle des fichiers API

| Fichier | Rôle |
| --- | --- |
| `config/adapters/inbound/fastapi.yaml` | Configure le transport HTTP généré par Arclith. |
| `adapters/inbound/schemas/todo_schema.py` | Définit les payloads et réponses HTTP. C'est le contrat exposé dans Swagger, pas le modèle métier. |
| `adapters/inbound/fastapi/handlers/todo_handlers.py` | Traduit HTTP vers `CreateTodoCommand` et `ListTodosQuery`, puis traduit les résultats en réponses Arclith. |
| `adapters/inbound/fastapi/routers/todo_router.py` | Déclare les routes, métadonnées OpenAPI, exemples, headers et statuts HTTP. |
| `adapters/inbound/fastapi/register.py` | Récupère les use cases via le container et branche le router dans l'application FastAPI. |
| `main.py` | Crée l'instance `Arclith`, l'application FastAPI et lance le transport API. |

Le handler voit les ports inbound; le router voit FastAPI; aucun des deux ne manipule directement
`Repository[Todo]`.

Étape suivante: [configurer FastAPI et les schémas HTTP](04-api-config-schemas.md).
