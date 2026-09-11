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
applicatives. La projection FastAPI les traduit respectivement en `404` et
`409`; cette traduction reste dans l'adapter et n'appartient pas aux use cases.

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

# Projection explicite des cinq opérations
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

`expose-feature` exige que l'adapter FastAPI soit déjà installé. La commande ne
crée ni adapter ni persistence et consomme le manifeste canonique
`.arclith/features/todo.yaml` sans déduire le CRUD depuis les noms de fichiers.
Elle planifie les cinq bindings ensemble avant la première écriture : une
collision sur une seule opération rejette donc toute la projection.

Sans `--path`, le chemin déterministe utilise la feature en kebab-case :
`todo` devient `/v1/todo` et `shopping_item` devient `/v1/shopping-item`. La CLI
ne pluralise pas un nom métier ; fournir `--path /v1/todos` rend le contrat
public explicite.

## Contrat FastAPI Généré

| Méthode | Chemin | Succès | Erreurs applicatives |
|---|---|---:|---|
| `POST` | `/v1/todos` | `201` + `CreateTodoResponse` | validation `422` |
| `GET` | `/v1/todos/{uuid}` | `200` + `GetTodoResponse` | `404`, validation `422` |
| `GET` | `/v1/todos?offset=0&limit=100` | `200` + `ListTodoResponse` | validation `422` |
| `PATCH` | `/v1/todos/{uuid}` | `200` + `UpdateTodoResponse` | `404`, `409`, validation `422` |
| `DELETE` | `/v1/todos/{uuid}` | `200` + `DeleteTodoResponse` | `404`, validation `422` |

Le paramètre `uuid` est extrait du chemin et réinjecté par le mapper dans la
Command ou Query applicative ; il n'est pas dupliqué dans le body ou la query
string. `PATCH` et `DELETE` répondent avec un body typé, donc utilisent `200`
plutôt que `204`. Changer cette convention exige de versionner explicitement le
contrat et son presenter.

Les contrats et routes sont créés une fois puis deviennent propriété du projet.
Les registres, le composition root et le manifeste de bindings restent générés.
Une relance préserve les personnalisations et n'ajoute pas une seconde étape de
recette. Utiliser `--dry-run` pour revoir tout le plan sans écriture.

FastAPI est la seule projection de feature fournie dans cette version. Les
projections MCP, RabbitMQ ou LangGraph restent des décisions séparées à concevoir
selon leur sémantique propre ; elles ne doivent pas recopier mécaniquement REST.
