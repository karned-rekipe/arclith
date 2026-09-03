# Capability Repository

## Intention

La capability outbound `repository` persiste les entités métier et leur cycle
de vie derrière le port commun `Repository[T]`. Le domaine et les use cases ne
dépendent ni de MongoDB, ni d'un moteur SQL, ni d'un format de fichier.

Utiliser un repository pour la source de vérité CRUD d'une entité. Ne pas
l'utiliser pour stocker directement un fichier volumineux, calculer un
embedding ou maintenir un index vectoriel reconstruisible.

## Position Hexagonale

```text
adapter inbound -> port inbound -> use case -> Repository[T]
                                             -> FileStoragePort
                                             -> VectorStorePort
```

Chaque port correspond à une responsabilité différente :

| Besoin | Capability | Responsabilité |
|---|---|---|
| conserver une entité métier et son cycle de vie | `repository` | source de vérité CRUD |
| conserver un fichier ou un blob original | [`storage`](storage.md) | octets et métadonnées objet |
| retrouver les voisins d'un vecteur | [`vector-store`](vector-store.md) | index de recherche reconstruisible |

### Pourquoi SQL Et NoSQL Restent Une Même Capability

SQL et NoSQL décrivent ici des familles d'implémentation et de garanties, pas
deux responsabilités métier. `Repository[T]` reste donc le port commun tant que
le contrat est centré sur les entités et le CRUD.

Créer maintenant `sql-repository` et `nosql-repository` dupliquerait le même
port sans donner de capacité supplémentaire aux use cases. Un port relationnel
spécifique ne deviendrait pertinent que si Arclith devait exposer explicitement
des transactions applicatives, des contraintes uniques, des requêtes typées,
des relations ou joins, des migrations, ou des schémas structurés par champ.

`storage` reste séparé parce qu'il conserve les blobs originaux.
`vector-store` reste séparé parce qu'il conserve un index ou une projection de
recherche, et non la source de vérité métier par défaut.

## Quickstart

Afficher le catalogue lisible par une personne ou exploitable par un outil :

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

Ajouter un adapter à un projet :

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mongodb \
  --yes
```

L'adapter actif reste choisi par la configuration existante :

```yaml
# config/adapters/adapters.yaml
repository: mongodb
```

Les facets sont uniquement des métadonnées de choix dans le catalogue CLI.
Elles ne changent ni ce fichier, ni le contrat du port, ni le comportement des
projets existants.

Voir aussi le [quickstart historique](../quickstart.md) pour le wizard complet.

## Formation

Le projet Todo montre le chemin complet :

1. [initialiser le projet avec `repository: memory`](../tutorials/todo-list/01-init-project.md) ;
2. [faire dépendre les use cases du port](../tutorials/todo-list/03-create-usecase.md) ;
3. [passer à MongoDB pour partager l'état entre processus](../tutorials/todo-list/07-local-services.md).

## Contrat

`Repository[T]` fournit le même contrat quel que soit l'adapter :

| Méthode | Rôle |
|---|---|
| `create(entity)` | persister une nouvelle entité |
| `read(uuid)` | lire une entité, supprimée logiquement ou non |
| `update(entity)` | remplacer l'état persistant de l'entité |
| `delete(uuid)` | supprimer physiquement une entité |
| `find_all()` | lister les entités non supprimées |
| `find_page(offset, limit)` | paginer les entités non supprimées avec leur total |
| `find_deleted()` | lister les entités supprimées logiquement |
| `duplicate(uuid)` | créer une copie avec un nouvel UUID |

Le choix de l'adapter passe par `build_repository()` et `Arclith.repository()`.
Les adapters inbound ne doivent jamais instancier une implémentation concrète.

### Contrat JSON Des Facets

Chaque adapter repository expose un objet `facets` dans
`arclith-cli capabilities --json` :

```json
{
  "storage_model": "document",
  "runtime": "server",
  "production_ready": true,
  "multi_process": true,
  "transactions": "limited",
  "schema_strategy": "flexible",
  "recommended_for": [
    "API, MCP et agents avec état partagé"
  ],
  "limits": [
    "pas de modèle relationnel riche via Repository[T]"
  ]
}
```

La forme est stable et entièrement sérialisable :

| Facet | Valeurs | Lecture |
|---|---|---|
| `storage_model` | `memory`, `document`, `relational_json`, `embedded_analytics`, `relational_structured` | famille de persistance |
| `runtime` | `in_process`, `file`, `server` | emplacement et durée de vie du moteur |
| `production_ready` | booléen | adapter destiné ou non à un runtime de production |
| `multi_process` | booléen | état partageable entre plusieurs processus applicatifs |
| `transactions` | `none`, `limited`, `strong` | niveau transactionnel réellement accessible via l'adapter |
| `schema_strategy` | `flexible`, `json_table`, `structured_tables` | façon dont les entités sont matérialisées |
| `recommended_for` | liste de chaînes | usages conseillés |
| `limits` | liste de chaînes | compromis à vérifier avant sélection |

`strong` signifie que chaque opération repository s'exécute dans une
transaction forte du moteur. Le port ne fournit toutefois pas d'unité de
travail permettant de regrouper plusieurs appels dans une même transaction.
`limited` couvre une atomicité limitée à l'opération ou aux garanties propres
au moteur, sans transaction applicative multi-opérations exposée.

Les autres capabilities peuvent laisser `facets` à `null`. Cela permet
d'étendre progressivement le catalogue sans imposer artificiellement ces axes
de persistance aux adapters inbound ou runtime.

## Adapters

### Matrice De Choix

| Adapter | Famille et runtime | Usage recommandé | Limite principale |
|---|---|---|---|
| `memory` | mémoire / processus | tests, smoke, développement local mono-processus | volatile et non partagé entre processus |
| `mongodb` | document / serveur | état métier partagé, modèle document-first ou évolutif | pas de modèle relationnel riche via le port |
| `duckdb` | analytique embarqué / fichier | démonstrations et traitements analytiques locaux | pas une base applicative serveur multi-processus |
| `mariadb` | relationnel avec payload JSON / serveur | intégration à un SI MariaDB existant | entité stockée en JSON, sans mapping relationnel métier riche |
| `postgresql` | relationnel avec payload JSONB / serveur | SQL serveur robuste et état partagé | entité stockée en JSONB, sans mapping relationnel métier riche |

### Matrice Des Garanties

| Adapter | Production ready | Multi-processus | Transactions | Stratégie de schéma |
|---|---:|---:|---|---|
| `memory` | non | non | `none` | `flexible` |
| `mongodb` | oui | oui | `limited` | `flexible` |
| `duckdb` | non | non | `limited` | `structured_tables` |
| `mariadb` | oui | oui | `strong` | `json_table` |
| `postgresql` | oui | oui | `strong` | `json_table` |

`production_ready` décrit la cible de l'adapter Arclith, pas une certification
automatique du déploiement. La haute disponibilité, les sauvegardes, la
réplication, le chiffrement et les tests de charge restent à valider dans
l'infrastructure du service.

### Memory

`memory` n'a pas de fichier scoped. Il est le choix par défaut pour les tests
rapides, mais chaque processus possède son propre état et toute donnée est
perdue à son arrêt.

### MongoDB

```yaml
# config/adapters/outbound/mongodb.yaml
uri: null
db_name: my_service
collection_name: null
multitenant: false
```

`uri: null` signifie que l'URI doit venir de `config/secrets.yaml`, de
l'environnement ou de Vault. MongoDB convient à un état partagé document-first
et à un schéma évolutif. Le port n'expose ni jointure relationnelle, ni
transaction regroupant plusieurs appels repository.

### DuckDB

```yaml
# config/adapters/outbound/duckdb.yaml
multitenant: false
path: data/
```

L'adapter matérialise l'entité dans une table DuckDB puis la persiste dans un
fichier supporté. Il cible les démonstrations ou traitements analytiques
locaux. Ne pas le choisir comme base applicative serveur partagée par défaut.

### MariaDB

```yaml
# config/adapters/outbound/mariadb.yaml
url: null
host: 127.0.0.1
port: 3306
database: my_service
user: app
password: null
driver: asyncmy
table_prefix: ""
multitenant: false
```

Chaque entité est stockée dans une table générique avec les champs techniques
et un payload JSON. Cet adapter réutilise les transactions du moteur pour
chaque opération, sans exposer de modèle relationnel métier ni d'unité de
travail multi-opérations.

### PostgreSQL

```yaml
# config/adapters/outbound/postgresql.yaml
url: null
host: 127.0.0.1
port: 5432
database: my_service
user: app
password: null
schema: public
driver: asyncpg
table_prefix: ""
multitenant: false
```

PostgreSQL suit le même port avec une table générique par type et un payload
JSONB. L'adapter cible un serveur SQL durable et multi-processus. Les colonnes
métier typées, Alembic, les joins et les contraintes SQL métier restent hors du
contrat actuel.

## Production

Choisir l'adapter à partir des garanties nécessaires :

1. rester sur `memory` si le processus peut perdre son état et ne le partage
   avec aucun autre runtime ;
2. choisir `duckdb` si le fichier local et l'usage analytique embarqué sont des
   contraintes explicites ;
3. choisir `mongodb` pour un modèle document-first partagé et évolutif ;
4. choisir `mariadb` lorsqu'un SI MariaDB existe déjà ;
5. choisir `postgresql` pour un backend SQL serveur général avec payload JSONB.

Les URI et mots de passe passent par la capability [`secrets`](secrets.md), par
exemple `MONGODB_URI`, `MARIADB_URL`, `MARIADB_PASSWORD`, `POSTGRESQL_URL` ou
`POSTGRESQL_PASSWORD`. Ne pas les écrire en clair dans les fichiers versionnés.

Pour plusieurs réplicas API, MCP ou agent, sélectionner un adapter
`multi_process: true`. Cette facet ne remplace pas la validation de la capacité
du moteur, de son pool de connexions et de son déploiement à absorber la charge.

## Validation

Vérifier le contrat des facets et la sortie CLI :

```bash
uv run --directory cli pytest tests/test_capabilities.py -q
uv run --directory cli arclith-cli capabilities --json
```

Avant contribution :

```bash
make quality
make docs
```

## Troubleshooting

### Deux Processus Ne Voient Pas Le Même État

Vérifier `multi_process` dans la sortie JSON. `memory` et `duckdb` ne sont pas
les choix par défaut pour partager l'état entre API, MCP, agents ou workers.

### Une Facet Vaut `null`

Les facets de cette matrice sont renseignées pour les adapters `repository`.
Une autre capability peut retourner `null` tant qu'elle ne dispose pas d'une
taxonomie adaptée à sa responsabilité.

### Un Backend SQL N'Expose Pas De Joins Métier

`mariadb` et `postgresql` implémentent aujourd'hui le port CRUD entity-first et
stockent un payload JSON ou JSONB générique. Une application qui exige des
requêtes relationnelles typées, des contraintes métier ou des transactions
multi-agrégats doit définir un port applicatif dédié dans son propre domaine.

## Projet

Le [projet Todo](../tutorials/todo-list/index.md) utilise `memory` dans les tests
et MongoDB pour partager les données entre les processus API, MCP et agent. Le
[chapitre services locaux](../tutorials/todo-list/07-local-services.md) montre
le passage de l'un à l'autre sans modifier les use cases.

## Suite

Lire [`storage`](storage.md) pour les fichiers, [`vector-store`](vector-store.md)
pour les projections de recherche, puis [`secrets`](secrets.md) pour les
credentials des adapters serveur.
