# Blueprints Applicatifs

Un blueprint applicatif accélère un cas d'usage récurrent sans le confondre avec
une technologie. Il génère une structure initiale cohérente dans le domaine,
l'application, la composition et les tests. Le projet reste propriétaire de ces
fichiers et doit y ajouter ses règles métier.

CRUD, append-only, state-machine, job, synchronization et workflow sont les six blueprints fournis par
Arclith. Le CRUD n'est ni le modèle universel d'une entité, ni une capability,
ni un adapter. `state-machine` décrit l'état métier d'un agrégat ; il ne doit pas
être confondu avec un workflow d'exécution. D'autres familles pourront être
ajoutées indépendamment, par exemple une recherche,
une conversation ou un pipeline RAG.

## Trois Niveaux Distincts

| Niveau | Question | Exemples | Commande |
|---|---|---|---|
| Blueprint applicatif | Quel comportement récurrent initialiser ? | CRUD, append-only, state-machine, job, synchronization, workflow | `add-blueprint` |
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

Le blueprint state-machine utilise le manifeste version 2. Il ajoute le mapping
`parameters` résolu et des digests SHA-256 du template et de la configuration.
La recette et le manifeste embarquent les valeurs canoniques, jamais le chemin
absolu du fichier `--spec`. Les manifests version 1 CRUD et append-only restent
lisibles et rejouables tels quels, sans migration implicite.

Le blueprint [job](blueprints/job.md) utilise le manifeste V3 pour distinguer
`target: {kind: standalone}` et `target: {kind: entity, entity: {name, module}}`.
Il exige une spec et un choix explicite `--entity` ou `--no-entity`. Le mode
standalone exige aussi `--feature`. Les quatre profils d'entité du menu ci-dessus
restent inchangés : un job est un modèle d'exécution, pas un profil d'entité.

```bash
arclith-cli add-blueprint job --feature report_generation \
  --no-entity --spec report-job.yaml
```

Le blueprint [synchronization](blueprints/synchronization.md) réutilise Job pour
une réconciliation pull full/incremental. Il conserve le manifeste V2, exige une
entité existante et une spec, et expose quatre opérations. Le mapper, les ports
source/cible et le checkpoint sont injectés explicitement ; la génération
préserve le modèle métier existant.

```bash
arclith-cli add-blueprint synchronization --entity Customer \
  --feature customer_sync --spec customer-sync.yaml
```

Le blueprint [workflow](blueprints/workflow.md) réutilise les cibles du manifeste
V3. Il orchestre des étapes séquentielles injectées avec checkpoint après succès,
reprise explicite et clé d’exécution stable. Les étapes métier et la projection
du résultat restent à compléter. Le store/runner mémoire est non durable.

```bash
arclith-cli add-blueprint workflow --feature document_publication \
  --no-entity --spec document-publication-workflow.yaml
```

La sortie `arclith-cli blueprints --json` expose `parameterized` pour que les
outils sachent si une entrée externe comme `--spec` est requise, sans déduire ce
contrat d'une liste d'opérations vide.

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
[blueprint state-machine](blueprints/state-machine.md), le
[blueprint job](blueprints/job.md), le
[blueprint synchronization](blueprints/synchronization.md) et le
[blueprint workflow](blueprints/workflow.md) pour leurs contrats détaillés
et les [blueprints des adapters](deep-dives/adapter-blueprints.md) pour la
structure des implémentations techniques.
