# Le Chemin Hexagonal

Une fonctionnalité Arclith suit toujours le même chemin.

## Chemin

```text
Entrée utilisateur
  -> adapter inbound
  -> port inbound ou use case
  -> domaine
  -> port outbound
  -> adapter outbound
```

## Exemple API

```text
POST /v1/todos
  -> route FastAPI
  -> CreateTodoPort
  -> CreateTodoUseCase
  -> TodoRepository
  -> MongoDBRepository
```

## Exemple MCP

```text
tool create_todo
  -> tool FastMCP
  -> CreateTodoPort
  -> CreateTodoUseCase
  -> TodoRepository
  -> MongoDBRepository
```

## Règle

Un adapter inbound ne doit pas appeler un repository concret.

Il appelle un port inbound ou un use case. Le repository reste derrière un port outbound.

## Validation

Quand tu relis un fichier `adapters/inbound`, cherche les imports directs vers un adapter outbound :

```bash
rg "adapters\\.outbound" src/*/adapters/inbound
```

Cette commande ne doit pas révéler de contournement métier.

## Suite

Exécuter [Quickstart API](../quickstarts/api.md).
