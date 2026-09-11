# Blueprints Applicatifs

Un blueprint applicatif accélère un cas d'usage récurrent sans le confondre avec
une technologie. Il génère une structure initiale cohérente dans le domaine,
l'application, la composition et les tests. Le projet reste propriétaire de ces
fichiers et doit y ajouter ses règles métier.

Le CRUD est le premier blueprint fourni par Arclith. Ce n'est ni le modèle
universel d'une entité, ni une capability, ni un adapter. D'autres familles
pourront être ajoutées indépendamment, par exemple un workflow, une recherche,
un import, un traitement événementiel, une conversation ou un pipeline RAG.

## Trois Niveaux Distincts

| Niveau | Question | Exemples | Commande |
|---|---|---|---|
| Blueprint applicatif | Quel comportement récurrent initialiser ? | CRUD | `add-blueprint` |
| Capability | De quelle capacité technique le service a-t-il besoin ? | API, MCP, repository, agent | `capabilities` |
| Adapter | Avec quelle technologie implémenter la capability ? | FastAPI, FastMCP, MongoDB, PostgreSQL | `add-adapter` |
| Projection | Quel contrat public exposer sur un adapter installé ? | CRUD vers REST | `expose-feature` |

Une feature peut donc appliquer un blueprint CRUD tout en restant sans transport
et en utilisant le repository mémoire par défaut. FastAPI, FastMCP et un store
persistant sont des décisions explicites ultérieures.

## Découvrir Le Catalogue

```bash
arclith-cli blueprints
arclith-cli blueprints --json
```

La sortie JSON est stable et exploitable par un agent ou une CI. Chaque entrée
publie son nom, sa version et les opérations qu'elle initialise.

## Appliquer Un Blueprint

Lors de la création interactive d'une entité, la CLI propose un profil initial :

```text
Profil applicatif initial
  1. minimal
  2. crud
```

Le profil `minimal`, sélectionné par défaut, conserve le comportement historique :
seul le modèle est créé. Pour un script, un agent ou une CI, rendre la décision
explicite :

```bash
arclith-cli add-entity Todo --profile minimal
arclith-cli add-entity Todo --profile crud
arclith-cli new Todo todo-service --profile crud
```

Un blueprint peut aussi être appliqué après la création de l'entité :

```bash
arclith-cli add-blueprint crud --entity Todo
arclith-cli add-blueprint crud --entity Todo --feature todo --dry-run
```

`--feature` accepte un nom Python public en `snake_case`. Par défaut, il reprend
le nom normalisé de l'entité.

## Manifeste Et Propriété Des Fichiers

La première application écrit un manifeste canonique versionné :

```yaml
version: 1
feature: todo
entity:
  name: Todo
  module: todo_service.domain.models.todo
blueprint:
  name: crud
  version: 1
operations:
  - create
  - get
  - list
  - update
  - delete
```

Il est enregistré dans `.arclith/features/<feature>.yaml`. Ce manifeste permet
à une projection de transport de savoir quelles opérations existent, sans
déduire un comportement depuis le nom d'un fichier ou d'un adapter.

Après installation explicite de FastAPI, le CRUD peut être projeté comme un
ensemble REST cohérent :

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-feature todo --via fastapi --path /v1/todos --dry-run
arclith-cli expose-feature todo --via fastapi --path /v1/todos
```

Cette commande consomme le manifeste et prévalide les cinq opérations dans un
seul plan avant toute écriture. Elle ne crée jamais l'adapter à la place de
`add-adapter`. Pour une opération isolée ou un comportement hors blueprint,
utiliser `expose-usecase`.

Les règles de génération sont strictes :

- avant la première installation, une collision avec un fichier applicatif
  existant arrête toute la génération ;
- après installation, un replay complète uniquement les fichiers manquants et
  préserve tous les fichiers existants ;
- un manifeste modifié ou incompatible doit être résolu explicitement ;
- `--dry-run` n'écrit ni fichier, ni manifeste, ni étape de recette ;
- aucune route, aucun tool MCP et aucun adapter de persistence ne sont créés
  implicitement ; une route n'apparaît qu'après `expose-feature` ou
  `expose-usecase`.

Consulter le [blueprint CRUD](blueprints/crud.md) pour son contrat détaillé et
les [blueprints des adapters](deep-dives/adapter-blueprints.md) pour la structure
des implémentations techniques.
