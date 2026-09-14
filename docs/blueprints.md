# Blueprints Applicatifs

Un blueprint applicatif accélère un cas d'usage récurrent sans le confondre avec
une technologie. Il génère une structure initiale cohérente dans le domaine,
l'application, la composition et les tests. Le projet reste propriétaire de ces
fichiers et doit y ajouter ses règles métier.

CRUD, append-only et state-machine sont les trois blueprints fournis par
Arclith. Le CRUD n'est ni le modèle universel d'une entité, ni une capability,
ni un adapter. `state-machine` décrit l'état métier d'un agrégat ; il ne doit pas
être confondu avec un workflow d'exécution. D'autres familles pourront être
ajoutées indépendamment, par exemple un job, une synchronisation, une recherche,
une conversation ou un pipeline RAG.

## Trois Niveaux Distincts

| Niveau | Question | Exemples | Commande |
|---|---|---|---|
| Blueprint applicatif | Quel comportement récurrent initialiser ? | CRUD, append-only, state-machine | `add-blueprint` |
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
  3. append-only
  4. state-machine
```

Le profil `minimal`, sélectionné par défaut, conserve le comportement historique :
seul le modèle est créé. Pour un script, un agent ou une CI, rendre la décision
explicite :

```bash
arclith-cli add-entity Todo --profile minimal
arclith-cli add-entity Todo --profile crud
arclith-cli new Todo todo-service --profile crud
arclith-cli add-entity Measurement --profile append-only
arclith-cli add-entity Invoice --profile state-machine \
  --spec invoice-lifecycle.yaml
```

Un blueprint peut aussi être appliqué après la création de l'entité :

```bash
arclith-cli add-blueprint crud --entity Todo
arclith-cli add-blueprint crud --entity Todo --feature todo --dry-run
arclith-cli add-blueprint state-machine --entity Invoice \
  --feature invoice_lifecycle --spec invoice-lifecycle.yaml
```

`--feature` accepte un nom Python public en `snake_case`. Par défaut, il reprend
le nom normalisé de l'entité. Pour CRUD, cette seconde forme est recommandée
après avoir défini les champs du modèle : le blueprint les projette alors dans
les commandes de création et de mise à jour avec leurs contraintes Pydantic.
Les fichiers générés restent des instantanés détenus par le projet et ne sont
pas resynchronisés implicitement après personnalisation.

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

Les blueprints paramétrés utilisent le manifeste version 2. Il ajoute le mapping
`parameters` résolu et des digests SHA-256 du template et de la configuration.
La recette et le manifeste embarquent les valeurs canoniques, jamais le chemin
absolu du fichier `--spec`. Les manifests version 1 CRUD et append-only restent
lisibles et rejouables tels quels, sans migration implicite.

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

Le profil `append-only` crée un `ImmutableRecord` distinct de l'`Entity` CRUD.
Sa seule opération est `append` ; son store est injecté explicitement et aucun
transport ni query n'est ajouté. Il ne transforme pas un modèle mutable existant.

Le profil `state-machine` crée une `Entity` dont le champ d'état typé est protégé
contre l'affectation directe. Chaque transition de la spec devient un verbe, un
port et un use case explicites. Le projet fournit un port outbound CAS ; Arclith
ne prétend pas rendre atomique un repository qui ne possède pas ce contrat.

Consulter le [blueprint CRUD](blueprints/crud.md), le
[blueprint append-only](blueprints/append-only.md), le
[blueprint state-machine](blueprints/state-machine.md) pour leurs contrats détaillés
et les [blueprints des adapters](deep-dives/adapter-blueprints.md) pour la
structure des implémentations techniques.
