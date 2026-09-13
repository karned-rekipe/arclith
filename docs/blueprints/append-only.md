# Blueprint Append-only

Le blueprint `append-only` version 1 initialise une feature de faits immuables :
mesures, observations, écritures ou audits. Il offre une seule opération,
`append`, sans adapter de transport implicite.

## Choisir Le Bon Modèle

| Modèle | Responsabilité | Primitives |
|---|---|---|
| CRUD | Modifier l'état courant d'une entité | `Entity`, `Repository[T]` |
| Append-only | Ajouter un fait sans réécrire le passé | `ImmutableRecord`, `AppendOnlyStore[T]` |
| Event sourcing | Reconstruire un agrégat depuis ses événements | Hors de ce blueprint |

`ImmutableRecord` n'hérite pas d'`Entity` : il ne porte ni version d'optimistic
locking, ni audit de modification, ni soft-delete. Le port n'expose aucun
`update`, `delete`, `restore`, `purge` ou `append_many`. Les queries et les
projections de lecture sont des features séparées : elles ne doivent pas ouvrir
une voie de modification des faits enregistrés.

## Générer Une Feature

```bash
arclith-cli init measurement-service
cd measurement-service
arclith-cli blueprints --json
arclith-cli add-entity Measurement --profile append-only
uv sync
uv run pytest tests/application -q
```

`minimal` reste le profil par défaut. Le profil `append-only` crée un modèle
basé sur `ImmutableRecord`, ses commandes/résultats et port inbound, le use case
d'append, un container, des tests et une documentation locale. `new Measurement
measurement-service --profile append-only` est le raccourci équivalent.

Pour un record déjà déclaré dans `domain/models/`, appliquer uniquement la feature :

```bash
arclith-cli add-blueprint append-only --entity Measurement \
  --feature measurement_ingestion --dry-run
arclith-cli add-blueprint append-only --entity Measurement \
  --feature measurement_ingestion
```

Cette seconde forme exige une classe héritant directement de l'`ImmutableRecord`
d'Arclith, sans redéfinir ses champs techniques ou sa configuration. Les imports
aliasés ou qualifiés sont reconnus sans exécuter le code du projet. Une `Entity`
mutable est refusée ; inversement, le blueprint CRUD refuse un `ImmutableRecord`.
Les classes décorées ou les héritages/configurations personnalisés demandent une
composition manuelle explicite.

La feature utilise les erreurs du framework ; aucun fichier de copie des erreurs
génériques n'est nécessaire. Les fichiers générés appartiennent au projet. Les
tests du profil neuf démontrent l'append idempotent ; pour un modèle qui déclare
déjà des champs métier, le test généré vérifie le contrat et la composition sans
inventer de valeurs. Ajouter alors ses scénarios métier représentatifs.

## Identité Et Temps

```python
from arclith.domain.models.immutable_record import ImmutableRecord


class Measurement(ImmutableRecord):
    sensor: str
    value: float
```

- `uuid` est un UUIDv7 généré par défaut, ou un UUID valide fourni par l'appelant.
  Il identifie le fait, pas sa tentative de livraison.
- `occurred_at` est obligatoire et représente le temps métier. Il exige un fuseau
  horaire et est normalisé en UTC.
- `recorded_at` vaut `None` avant l'append. Le store lui attribue son horodatage UTC
  au premier enregistrement, même si l'appelant a fourni une autre valeur.
  Un rejeu retourne l'horodatage initial ; le record d'entrée n'est pas modifié.

La configuration Pydantic `frozen` interdit la réaffectation des champs. Elle ne
rend pas les listes/dictionnaires imbriqués immuables. Le store mémoire prend une
copie profonde à l'entrée et retourne des copies profondes : modifier une
collection d'entrée, de résultat ou d'inspection ne change pas le fait stocké.
Préférer des tuples et des sous-modèles `frozen` dans les contrats applicatifs.

## Composer Et Rejouer

Le use case dépend du port outbound `AppendOnlyStore[Measurement]`. Le container
généré demande explicitement un store à son appelant. Le store append-only n'est
pas un `Repository` : il n'est ni sélectionné par `build_repository()` ni installé
par `add-adapter --capability repository`.

Exemple avec les modules du profil par défaut :

```python
from datetime import UTC, datetime
from uuid import UUID

from arclith.adapters.outbound.memory.append_only_store import InMemoryAppendOnlyStore
from arclith.domain.ports.outbound.append_only_store import AppendStatus
from measurement_service.domain.models.measurement import Measurement
from measurement_service.domain.ports.inbound.append_measurement import AppendMeasurementCommand
from measurement_service.infrastructure.containers.measurement import build_measurement_use_cases


async def ingest() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    use_cases = build_measurement_use_cases(store)
    command = AppendMeasurementCommand(
        record=Measurement(
            uuid=UUID("01951234-5678-7abc-8ef0-123456789abc"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        idempotency_key="measurement-001",
    )
    first = await use_cases.append.execute(command)
    retry = await use_cases.append.execute(command)
    assert first.status is AppendStatus.APPENDED
    assert retry.status is AppendStatus.DUPLICATE
    assert retry.record == first.record
```

Si vous avez ajouté les champs `sensor` et `value` de l'exemple de modèle plus
haut, fournissez-les aussi dans la commande. Un retry doit conserver **le même
UUID et le même temps métier**, pas reconstruire un record avec un nouvel UUID
automatique. Conserver la même instance de store pour toutes les requêtes d'un
même périmètre d'idempotence ; ne pas en créer une par requête.

| Situation | Résultat |
|---|---|
| Nouvelle clé et nouvel UUID | `AppendResult(status="appended", record=...)` |
| Même clé, même type de record et même contenu canonique | `duplicate`, copie du fait initial |
| Même clé, autre contenu ou autre type de record | `IdempotencyConflict` |
| UUID déjà stocké sous une autre clé | `RecordIdentityConflict` |
| Clé invalide | `InvalidIdempotencyKey` |
| Contenu non canonisable ou record non frozen | `AppendOnlyError` |
| Indisponibilité d'un futur store durable | `AppendStoreUnavailable` |

Les clés contiennent 1 à 255 caractères, sans espaces périphériques ni caractères
Unicode de catégorie `C` (contrôles, formats invisibles, etc.). Elles sont traitées
exactement, sans trim ni normalisation implicite. Leur unicité est locale au store.
Les erreurs ci-dessus n'incluent ni clé, ni payload. Aucun payload n'est journalisé
par le store ou le use case généré.

## Empreinte Canonique V1

`arclith.domain.services.append_only.record_fingerprint` fournit le calcul partagé :

1. Lire tous les champs Pydantic validés du record, y compris ceux déclarés avec
   `exclude=True`, et les éventuels extras. Exclure uniquement le `recorded_at`
   de premier niveau. L'UUID, `occurred_at` et les données métier sont inclus.
2. Convertir récursivement les valeurs : dictionnaires à clés chaîne, listes et
   tuples vers tableaux, sous-modèles vers leurs champs/extras, enums vers leur
   valeur, UUID/date/Decimal fini vers chaînes. Normaliser les datetimes aware en
   UTC avec `isoformat()`. Conserver null, booléens, entiers, chaînes et floats finis.
3. Sérialiser avec le JSON Python : `sort_keys=True`, `separators=(",", ":")`,
   `ensure_ascii=True`, `allow_nan=False`. Encoder en UTF-8, puis calculer SHA-256
   et préfixer l'hexadécimal par `sha256:`.

Les alias, serializers de présentation, champs calculés et attributs privés ne
définissent pas le contenu persistant. Un champ masqué par un serializer reste
comparé sur sa valeur validée. Les ensembles, bytes, `SecretStr`, dates-heures
naïves, nombres non finis et clés de dictionnaire non textuelles sont refusés.
La récursion est bornée à 64 niveaux afin de refuser aussi les cycles. Cette
convention JSON est celle du contrat V1, pas une promesse de canonicalisation
universelle de types Python arbitraires.

## Manifeste, Recettes Et Collisions

Le schéma de manifeste reste en version 1, sans secret, URI ou instance d'adapter :

```yaml
version: 1
feature: measurement_ingestion
entity:
  name: Measurement
  module: measurement_service.domain.models.measurement
blueprint:
  name: append-only
  version: 1
operations:
  - append
```

Il est écrit dans `.arclith/features/measurement_ingestion.yaml`. Avant une
première installation, un fichier applicatif existant, un répertoire cible ou un
parent bloquant annule le plan sans écriture partielle. Les liens symboliques
dans les cibles/parents générés sont refusés. Les `__init__.py` existants sont
préservés. Le replay complète les fichiers manquants sans écraser ceux du
développeur ; un manifeste incompatible est refusé. Le dry-run n'écrit ni fichiers,
ni manifeste, ni recette. Les recettes historiques sans profil restent `minimal`.

## Limites Et Corrections

`InMemoryAppendOnlyStore` est une référence de test, non durable. Son verrou
protège les coroutines d'une même boucle asyncio : deux appends concurrents de
la même clé ne créent pas deux faits. `inspect_records()` retourne des copies en
ordre d'insertion ; c'est un outil de test, pas un port de recherche.

Il n'y a ni synchronisation entre threads/processus, ni réplication, ni reprise
après redémarrage, ni éviction automatique. Les faits et clés occupent la mémoire
tant que le store existe. En production, fournir un store durable avec une
contrainte d'unicité et une transaction atomique sur clé, empreinte et fait. Aucun
adapter MongoDB/PostgreSQL, transport FastAPI/FastMCP/RabbitMQ/LangGraph, ordre
global, batch ou garantie exactly-once distribuée n'est livré dans cette V1.

Une correction est **un nouveau fait** avec sa propre identité et sa propre clé :
compensation, invalidation ou remplacement logique, en référençant le fait
initial dans le modèle métier. La projection de lecture interprète cette
relation ; l'ancien fait ne doit jamais être écrasé silencieusement.
