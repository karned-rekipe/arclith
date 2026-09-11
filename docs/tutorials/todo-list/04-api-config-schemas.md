# 4.1 Contrats et schémas FastAPI

`add-adapter api/fastapi` crée la configuration suivante :

```yaml
# config/adapters/inbound/fastapi.yaml
host: 127.0.0.1
port: 8120
reload: true
```

`expose-usecase` lit les types du port inbound au moment de l'exposition et
génère un snapshot de contrat dans :

```text
adapters/inbound/fastapi/contracts/create_todo.py
```

Ce module contient trois responsabilités pures :

- `CreateTodoRequest`, DTO d'entrée HTTP ;
- `to_application`, mapping vers `CreateTodoCommand` ;
- `CreateTodoResponse` et `present_result`, contrat de sortie indépendant du
  modèle de persistance.

Le dossier de feature contient aussi les points d'extension nommés
`schemas.py`, `mappers.py`, `presenters.py` et `openapi.py`. Il est interdit de
créer en parallèle un dossier global `adapters/inbound/schemas`, un
`helpers.py` ou un second modèle de route. Lorsqu'un mapping devient assez
riche pour être extrait du snapshot, il va dans le module de rôle correspondant.

Modifier d'abord le port applicatif et ses modèles Pydantic, puis régénérer ou
revoir explicitement le contrat de transport. Un contrat développeur existant
n'est jamais écrasé silencieusement.

Étape suivante : [comprendre le binding HTTP](04-api-handlers.md).
