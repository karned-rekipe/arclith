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

L'adapter global reste choisi par la configuration existante :

```yaml
# config/adapters/adapters.yaml
repository: mongodb
```

Il sert aussi de fallback pour toute entité qui n'a pas de binding explicite.
Un service mono-store n'a donc rien à modifier.

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

### Router Des Entités Vers Plusieurs Stores

Un même service peut conserver le fallback global tout en sélectionnant un
adapter pour certaines classes d'entité. La clé recommandée est toujours le
chemin Python complet `<module>.<qualname>` :

```yaml
# config/adapters/adapters.yaml
repository: mongodb

repository_bindings:
  my_service.domain.models.chat.ChatThread: mongodb
  my_service.domain.models.chat.ChatMessage: mongodb
  my_service.domain.models.identity.UserAccount: mariadb
```

Les sections configurant ces deux adapters restent dans leurs fichiers scoped :

```yaml
# config/adapters/outbound/mongodb.yaml
uri: null
db_name: chat_service
collection_name: null
multitenant: false
```

```yaml
# config/adapters/outbound/mariadb.yaml
url: null
host: 127.0.0.1
port: 3306
database: identity_service
user: app
password: null
driver: asyncmy
table_prefix: identity_
multitenant: false
```

L'assemblage public ne change pas :

```python
chat_threads = arclith.repository(ChatThread)  # mongodb
chat_messages = arclith.repository(ChatMessage)  # mongodb
users = arclith.repository(UserAccount)  # mariadb
```

Le routing est exact et déterministe. Arclith construit la clé avec
`f"{entity_class.__module__}.{entity_class.__qualname__}"`. Il n'interprète pas
les noms courts, ce qui évite les collisions entre deux classes portant le même
nom. Si la classe n'est pas bindée, `repository` reste le fallback. Si elle est
bindée vers un adapter absent du registry utilisé, la construction échoue au
lieu de revenir silencieusement au fallback.

Les adapters intégrés `mongodb`, `duckdb`, `mariadb` et `postgresql` exigent
leur section de configuration dès qu'ils sont référencés par le fallback ou un
binding. Un nom custom reste possible avec un `RepositoryRegistry` applicatif ;
sa présence dans ce registry est contrôlée lors de la construction.

Les use cases continuent à dépendre uniquement des ports :

```python
class StartChatUseCase:
    def __init__(
        self,
        user_repository: Repository[UserAccount],
        thread_repository: Repository[ChatThread],
    ) -> None:
        self.user_repository = user_repository
        self.thread_repository = thread_repository
```

Le container connaît les classes et assemble les repositories. Le use case
sait qu'il coordonne deux ports, mais ne connaît ni MongoDB ni MariaDB.

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
| `postgresql` | JSONB par défaut, colonnes typées opt-in / serveur | SQL serveur robuste, contraintes et index ciblés | mapper et migrations structurées restent à la charge de l'application |

### Matrice Des Garanties

| Adapter | Production ready | Multi-processus | Transactions | Stratégie de schéma |
|---|---:|---:|---|---|
| `memory` | non | non | `none` | `flexible` |
| `mongodb` | oui | oui | `limited` | `flexible` |
| `duckdb` | non | non | `limited` | `structured_tables` |
| `mariadb` | oui | oui | `strong` | `json_table` |
| `postgresql` | oui | oui | `strong` | `json_table` par défaut, `structured_tables` opt-in |

`production_ready` décrit la cible de l'adapter Arclith, pas une certification
automatique du déploiement. La haute disponibilité, les sauvegardes, la
réplication, le chiffrement et les tests de charge restent à valider dans
l'infrastructure du service.

La facet PostgreSQL décrit le chemin par défaut `generic_json`. Une application
peut sélectionner `structured` pour une entité sans changer le port
`Repository[T]` ; le catalogue ne prétend pas qu'un unique schéma physique
s'applique à toutes les configurations possibles.

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
mapping_strategy: generic_json
auto_create_schema: true
multitenant: false
```

PostgreSQL suit le même port avec une table générique par type et un payload
JSONB par défaut. L'adapter cible un serveur SQL durable et multi-processus.
Une application peut opter explicitement pour des colonnes typées avec le
mécanisme décrit ci-dessous. Les relations automatiques, les joins, une query
DSL et la gestion des migrations restent hors du contrat Arclith.

## Mapping Relationnel Structuré Optionnel

### Quand L'utiliser

Conserver `mapping_strategy: generic_json` tant qu'une entité est naturellement
document-first et que les champs techniques suffisent pour les opérations du
repository. C'est le comportement backward-compatible et le chemin recommandé
pour démarrer.

Choisir `structured` seulement lorsqu'un besoin vérifié exige une représentation
relationnelle : contrainte `UNIQUE`, index métier, reporting SQL sur des colonnes
typées, compatibilité avec une table existante ou optimisation d'une requête
ciblée. Le mapper appartient alors à l'application et à son assemblage
d'infrastructure ; l'entité métier n'importe ni SQLAlchemy ni PostgreSQL.

Cette première itération exécute le mapping structuré uniquement dans l'adapter
`postgresql`. MariaDB conserve son stockage JSON générique. Sa configuration
n'accepte pas `mapping_strategy: structured` tant qu'un support équivalent n'a
pas été implémenté et testé.

### Déclarer Un Mapper

Le contrat public est pur Python et peut être importé directement depuis
`arclith` :

```python
from collections.abc import Mapping
from typing import Any

from arclith import (
    Entity,
    RelationalColumn,
    RelationalIndex,
)


class UserAccount(Entity):
    email: str
    display_name: str


class UserAccountMapper:
    entity_class = UserAccount
    table_name = "user_accounts"
    columns = (
        RelationalColumn("uuid", "uuid", primary_key=True),
        RelationalColumn("email", "string", unique=True, indexed=True),
        RelationalColumn("display_name", "string"),
        RelationalColumn("created_at", "datetime", indexed=True),
        RelationalColumn("updated_at", "datetime"),
        RelationalColumn("deleted_at", "datetime", nullable=True, indexed=True),
        RelationalColumn("version", "integer"),
    )
    indexes = (
        RelationalIndex(
            "ix_user_accounts_display_created",
            ("display_name", "created_at"),
        ),
    )

    def to_record(self, entity: UserAccount) -> Mapping[str, Any]:
        return {
            "uuid": entity.uuid,
            "email": entity.email,
            "display_name": entity.display_name,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def from_record(self, record: Mapping[str, Any]) -> UserAccount:
        return UserAccount(**dict(record))
```

Les kinds supportés sont `uuid`, `string`, `integer`, `float`, `boolean`,
`date`, `datetime` et `json`. PostgreSQL matérialise `json` en `JSONB` et les
dates/heures avec un type timezone-aware.

Pour préserver les opérations de `Repository[T]`, chaque mapper déclare les
colonnes `uuid`, `created_at`, `updated_at`, `deleted_at` et `version` avec les
kinds correspondants. `uuid` est l'unique clé primaire et `deleted_at` est
nullable. Les noms de table, colonne et index sont des identifiants SQL sûrs ;
les doublons et les index pointant vers une colonne inconnue sont refusés dès
l'enregistrement.

`to_record()` doit retourner exactement les colonnes déclarées et le même UUID
que l'entité. `from_record()` doit restituer la classe d'entité attendue. Le
mapper doit inclure tous les champs applicatifs ou d'audit que le service veut
préserver ; Arclith ne génère pas implicitement les colonnes métier depuis le
modèle Pydantic.

### Enregistrer Et Câbler Le Mapper

Le registre utilise l'identité exacte de la classe, sans import magique ni nom
court :

```python
from arclith import RelationalMapperRegistry

mapper_registry = RelationalMapperRegistry()
mapper_registry.register(UserAccountMapper())

users = arclith.repository(
    UserAccount,
    mapper_registry=mapper_registry,
)
```

La configuration PostgreSQL associée sélectionne la stratégie :

```yaml
# config/adapters/outbound/postgresql.yaml
database: identity_service
schema: public
table_prefix: "identity_"
mapping_strategy: structured
auto_create_schema: false
```

Avec ce préfixe, le mapper ci-dessus cible la table
`public.identity_user_accounts`. Si `structured` est sélectionné sans mapper
enregistré pour `UserAccount`, la construction du repository échoue avec le
chemin Python complet de la classe. Les autres entités peuvent continuer à
utiliser le fallback ou un adapter distinct via `repository_bindings`.

`mapper_registry` s'applique au registry repository intégré. Une application
qui fournit déjà son propre `RepositoryRegistry` peut partir de
`default_repository_registry(EntityClass, mapper_registry=...)`, y enregistrer
ses factories supplémentaires, puis le passer comme `registry`. Cela garde une
source de wiring unique et évite deux registries concurrents dans le même appel.

### Création De Schéma Et Migrations

`auto_create_schema: true` conserve le comportement PostgreSQL historique :
SQLAlchemy exécute uniquement `CREATE SCHEMA IF NOT EXISTS` si nécessaire, puis
`create_all()` pour les tables absentes. Ce mode est pratique en développement
et dans les tests ; il ne modifie ni ne supprime une colonne existante.

En production, utiliser `auto_create_schema: false` et appliquer les migrations
avec l'outil choisi par l'application avant le démarrage. Dans ce mode, Arclith
n'exécute aucune création implicite. Toute modification de `columns`,
`indexes`, `unique`, `nullable`, `table_name`, `schema` ou `table_prefix` peut
nécessiter une migration explicite.

Arclith ne génère pas de révision Alembic, n'exécute pas d'`ALTER TABLE`, ne
compare pas le mapper au schéma vivant et ne promet aucune migration destructive
automatique. Le mapper décrit la forme attendue par l'adapter ; l'application
reste propriétaire du cycle de vie du schéma.

### Requêtes Métier Et Relations

Le mapping structuré n'ajoute aucune méthode à `Repository[T]`. Un besoin tel
que `find_by_email()` doit rester un port métier explicite implémenté par
l'application. De même, les relations, le lazy loading et les joins automatiques
ne font pas partie du mécanisme. Pour les agrégats et stores multiples, les
limites transactionnelles décrites plus bas restent inchangées.

## Production

Choisir l'adapter à partir des garanties nécessaires :

1. rester sur `memory` si le processus peut perdre son état et ne le partage
   avec aucun autre runtime ;
2. choisir `duckdb` si le fichier local et l'usage analytique embarqué sont des
   contraintes explicites ;
3. choisir `mongodb` pour un modèle document-first partagé et évolutif ;
4. choisir `mariadb` lorsqu'un SI MariaDB existe déjà ;
5. choisir `postgresql` pour un backend SQL serveur général avec payload JSONB ;
6. activer son mapping `structured` seulement si des colonnes, contraintes ou
   index métier apportent une valeur mesurable.

Les URI et mots de passe passent par la capability [`secrets`](secrets.md), par
exemple `MONGODB_URI`, `MARIADB_URL`, `MARIADB_PASSWORD`, `POSTGRESQL_URL` ou
`POSTGRESQL_PASSWORD`. Ne pas les écrire en clair dans les fichiers versionnés.

Pour plusieurs réplicas API, MCP ou agent, sélectionner un adapter
`multi_process: true`. Cette facet ne remplace pas la validation de la capacité
du moteur, de son pool de connexions et de son déploiement à absorber la charge.

### Limites Transactionnelles Cross-store

Le routing ne crée aucune transaction atomique entre deux bases :

- placer dans le même aggregate et le même store les entités qui doivent
  respecter un invariant fort dans une mutation atomique ;
- coordonner des aggregates distincts dans la couche applicative ;
- utiliser outbox, command bus, idempotence et compensation quand une opération
  distribuée doit tolérer les échecs partiels ;
- construire un query service, une projection ou un read model pour une lecture
  combinée, sans cacher un join cross-store derrière `Repository[T]`.

Le routing reste limité au bounded context du service. Traverser le domaine
d'un autre service passe par son API, son MCP, ses événements ou son command
bus, jamais par l'accès direct à son repository ou à sa base.

### Multitenant

Les bindings ne remplacent pas l'isolation tenant. Si le fallback ou au moins
un adapter bindé porte `multitenant: true`, le pipeline tenant est activé pour
le service. Les adapters tenant-aware tels que MongoDB, MariaDB et PostgreSQL
continuent à lire leurs coordonnées dans le contexte tenant existant. Les
bindings eux-mêmes ne contiennent ni URI ni credential.

## Validation

Vérifier le routing, la configuration, le contrat des facets et la sortie CLI :

```bash
uv run --frozen pytest -q \
  tests/units/infrastructure/test_config.py \
  tests/units/infrastructure/test_repository_factory.py \
  tests/units/test_arclith_repository.py
uv run --directory cli --frozen pytest tests/test_capabilities.py -q
uv run --directory cli --frozen arclith-cli capabilities --json
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

`mariadb` stocke un payload JSON générique ; `postgresql` utilise JSONB par
défaut et accepte un mapper structuré explicite. Une application qui exige des
requêtes relationnelles typées, des contraintes métier ou des transactions
multi-agrégats doit définir un port applicatif dédié dans son propre domaine.
Le mapping structuré PostgreSQL rend les colonnes disponibles à cet adapter
applicatif, mais n'élargit pas le port générique.

### Le Mapping Structuré Refuse De Démarrer

Vérifier que la configuration PostgreSQL contient
`mapping_strategy: structured`, que le `RelationalMapperRegistry` enregistre
exactement la classe passée à `arclith.repository()`, et que ce registre est
fourni via `mapper_registry`. Le message indique le chemin complet de l'entité
sans mapper. Si la table n'existe pas et que `auto_create_schema` vaut `false`,
appliquer la migration applicative avant de relancer le service.

### Un Binding Est Refusé

Vérifier d'abord que la clé correspond exactement au module et au `qualname` de
la classe. Pour un adapter intégré, vérifier ensuite que son fichier scoped est
présent. Pour un adapter custom, enregistrer le même nom dans le
`RepositoryRegistry` passé à `arclith.repository(...)`. Le message d'erreur de
construction indique l'entité, l'adapter sélectionné et les adapters disponibles.

## Projet

Le [projet Todo](../tutorials/todo-list/index.md) utilise `memory` dans les tests
et MongoDB pour partager les données entre les processus API, MCP et agent. Le
[chapitre services locaux](../tutorials/todo-list/07-local-services.md) montre
le passage de l'un à l'autre sans modifier les use cases.

## Suite

Lire [`storage`](storage.md) pour les fichiers, [`vector-store`](vector-store.md)
pour les projections de recherche, puis [`secrets`](secrets.md) pour les
credentials des adapters serveur.
