# Blueprint CRUD

Le blueprint `crud` initialise le cycle de vie applicatif classique d'une
entité : `create`, `get`, `list`, `update` et `delete`. Il compose les primitives
déjà fournies par Arclith, mais laisse les champs, invariants, autorisations et
politiques métier au projet généré.

## Créer La Feature

En une commande avec l'entité :

```bash
arclith-cli add-entity Todo --profile crud
```

Ou sur une entité existante :

```bash
arclith-cli add-blueprint crud --entity Todo --feature todo
```

Prévisualiser avant d'écrire :

```bash
arclith-cli add-blueprint crud --entity Todo --dry-run
```

## Fichiers Créés

Pour le package `todo_service`, la feature `todo` produit :

```text
.arclith/features/todo.yaml
src/todo_service/
├── domain/
│   ├── errors/todo.py
│   └── ports/inbound/
│       ├── create_todo.py
│       ├── get_todo.py
│       ├── list_todo.py
│       ├── update_todo.py
│       └── delete_todo.py
├── application/use_cases/
│   ├── create_todo.py
│   ├── get_todo.py
│   ├── list_todo.py
│   ├── update_todo.py
│   └── delete_todo.py
└── infrastructure/containers/todo.py
tests/application/test_todo_crud.py
docs/blueprints/todo-crud.md
```

Le document créé dans le projet est local à la feature. Il rappelle les points
à personnaliser avant d'exposer un contrat public.

## Contrat Des Opérations

| Opération | Entrée | Résultat | Comportement initial |
|---|---|---|---|
| `create` | `CreateTodoCommand` | `CreateTodoResult` | construit l'entité puis utilise `BaseService.create` |
| `get` | `GetTodoQuery` | `GetTodoResult` | retourne l'entité active ou lève `TodoNotFoundError` |
| `list` | `ListTodoQuery` | `ListTodoResult` | pagination par `offset` et `limit`, avec `total` |
| `update` | `UpdateTodoCommand` | `UpdateTodoResult` | vérifie la version attendue puis délègue l'incrément |
| `delete` | `DeleteTodoCommand` | `DeleteTodoResult` | applique la politique de soft delete configurée |

`duplicate` et `purge` existent dans les primitives génériques d'Arclith mais
ne font pas partie du CRUD. Ils doivent être ajoutés comme cas d'usage explicites
si le métier en a besoin.

## Personnalisation Obligatoire

Les commandes de création et de mise à jour sont volontairement valides avec
les seuls champs techniques d'`Entity`. Après avoir ajouté les champs métier au
modèle, reporter uniquement les champs modifiables dans `CreateTodoCommand` et
`UpdateTodoCommand`, puis placer les invariants dans le domaine.

Les erreurs `TodoNotFoundError` et `TodoVersionConflictError` sont des erreurs
applicatives. Une future projection FastAPI pourra les traduire en `404` et
`409`; une projection MCP pourra produire son propre résultat d'erreur. Cette
traduction n'appartient pas aux use cases.

Le contrôle de version généré évite une mise à jour manifestement obsolète dans
le processus courant. Le port `Repository[T]` générique ne garantit pas à lui
seul un compare-and-swap atomique entre plusieurs processus. Si le métier exige
cette garantie, définir un port outbound spécialisé et l'implémenter avec une
transaction adaptée à MongoDB ou PostgreSQL.

## Choisir Les Adapters Ensuite

La feature est immédiatement testable avec le repository mémoire configuré par
défaut. Les choix techniques restent séparés :

```bash
# Persistance durable, si nécessaire
arclith-cli add-adapter --capability repository --adapter mongodb --yes

# Transport, si nécessaire
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli add-adapter --capability mcp --adapter fastmcp --yes
```

Cette première version ne projette pas encore automatiquement les cinq opérations
vers un transport. Le manifeste `.arclith/features/todo.yaml` constitue le
contrat d'entrée prévu pour cette évolution, sans coupler le blueprint à un
adapter particulier.
