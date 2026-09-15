# Blueprint Synchronization

Le blueprint `synchronization` réconcilie une source externe vers une cible
locale. La V1 fournit une synchronisation **pull**, complète ou incrémentale,
avec mapping explicite, application idempotente, checkpoint par page et rapport.
Elle s'exécute comme un [job](job.md), avec les mêmes statuts et le même contrat
d'annulation. Les adapters CRM/ERP, le mapping métier et le stockage durable
restent à implémenter dans le projet.

Cette capacité est développée dans l'[issue #225](https://github.com/karned-rekipe/arclith/issues/225).
Elle est disponible à partir d’Arclith **0.32.0** et d’arclith-cli **0.29.0**,
publiés selon le [processus de release](../release.md).

## Choisir Ce Modèle

| Besoin | Contrat |
|---|---|
| Lire et modifier une entité à la demande | CRUD |
| Traiter un fichier une fois | Import spécifique, éventuellement exécuté comme job |
| Maintenir une cible cohérente avec une source de vérité | Synchronization |
| Suivre une unité de travail | Job ; utilisé ici pour l'exécution |
| Coordonner plusieurs étapes métier | Workflow, hors de cette V1 |

Un nom de synchronisation définit un périmètre exclusif : une seule exécution
peut y écrire à la fois. La clé externe identifie un élément **dans ce périmètre**.
Le mapper produit les champs possédés par la source (`owned_fields`) ; le port
cible doit conserver les autres champs locaux. `source_wins` s'applique à cette
liste explicite, sans copie automatique du payload source.

## Générer Une Feature

Depuis un répertoire de travail, utiliser les paquets publics :

```bash
uv tool install --upgrade arclith-cli==0.29.0

arclith-cli init customer-service
cd customer-service
arclith-cli add-entity Customer
cat > customer-sync.yaml <<'YAML'
version: 1
direction: pull
modes: [full, incremental]
external_key: external_id
page_size: 100
conflict_policy: source_wins
missing_policy: deactivate
execution: job
YAML

arclith-cli add-blueprint synchronization --entity Customer \
  --feature customer_sync --spec customer-sync.yaml --dry-run
arclith-cli add-blueprint synchronization --entity Customer \
  --feature customer_sync --spec customer-sync.yaml
uv sync --group dev
uv run python -m pytest tests -q
```

Le projet généré déclare `arclith>=0.32.0` et ses dépendances de test.
`uv sync` installe les paquets publics dans son propre environnement.

`synchronization` exige une entité mutable existante et une spec ; `--no-entity`
et `add-entity --profile synchronization` sont refusés. Le modèle `Customer`
n'est pas réécrit. Utiliser un nom de feature distinct du module de l'entité,
par exemple `customer_sync`, pour éviter une collision de fichiers.

Les huit champs YAML ci-dessus sont obligatoires. Les modes sont normalisés
dans un ordre stable. Trois paramètres supplémentaires sont possibles :

| Paramètre | Défaut | Limites / sens |
|---|---|---|
| `page_size` | 100 dans l'API Python | Entier de 1 à 1 000 ; obligatoire dans la spec |
| `max_full_items` | 10 000 | Entier de 1 à 100 000, borne des clés distinctes vues en full |
| `max_pages` | 1 000 | Entier de 1 à 10 000 par tentative, y compris les pages vides |
| `source_version` | `"1"` | Identifiant technique public de 1 à 80 caractères alphanumériques, `_`, `.` ou `-` |

Les booléens ne sont pas acceptés à la place d'entiers. Le YAML est limité à
64 KiB. Les champs inconnus, les noms Python réservés et les politiques non
supportées sont refusés avant écriture.

## Fichiers Et Composition

La feature génère :

- les modèles source et patch sous `domain/models/customer_sync.py` ;
- les quatre ports inbound et use cases `start_sync`, `get_sync_status`,
  `cancel_sync`, `get_sync_report` ;
- les ports outbound source, cible et checkpoint spécialisés ;
- `application/synchronization/customer_sync_mapper.py`, à compléter ;
- un container et `build_customer_sync_handler` pour assembler le JobHandler ;
- des tests avec fakes explicites et une documentation locale.

Les modèles initiaux déclarent uniquement la clé externe. Le projet ajoute ses
champs source et les champs qu'il autorise à modifier dans la cible. Le mapper
de production lève `NotImplementedError` ; les tests utilisent un mapping
d'identité volontaire, local au test. Les tests verts ne prétendent donc pas
valider une intégration métier encore absente.

Le container reçoit un `JobRunnerPort`, son `JobStorePort` et le checkpoint
spécialisé. Le handler reçoit la source, la cible et le mapper. Aucun transport,
broker ou adapter n'est installé. Le runner mémoire exécute uniquement sur
`await runner.run(job_id)` ; son propriétaire attend la tâche et collecte les
erreurs. Un futur runner durable peut utiliser le même handler.

La CLI conserve le **manifeste V2** pour cette feature liée à une entité, avec
paramètres normalisés et digests de template/configuration. La recette garde
son enveloppe V1, embarque les paramètres et n'a plus besoin du YAML original.
Les manifestes et sorties CRUD, append-only, state-machine et Job sont préservés.
Les collisions, les dérives et un framework incompatible sont contrôlés avant
publication ; le replay préserve les personnalisations existantes.

## Pages, Reprise Et Absence

La source reçoit `mode`, `cursor` et `limit`. L'application transmet le curseur
sans le parser. `next_cursor` désigne la page suivante ; `None` termine la
pagination. Une page incrémentale terminale contenant des éléments doit fournir
un **`checkpoint_cursor`**, le watermark à reprendre lors du prochain pull.
Cette distinction évite de perdre le point de reprise à la dernière page.
Une page terminale vide sans watermark conserve le curseur entrant.

Les clés doivent être uniques dans une page et, en full, sur toute l'énumération.
Une page répétant une clé est refusée avant son application : cela évite qu'un
retry rejoue plusieurs mises à jour contradictoires pour le même élément.
L'adapter doit garantir des pages stables sur le point de reprise ; un flux CDC
contenant plusieurs changements du même élément n'est pas ce contrat V1.

Le job suit cet ordre :

1. Revendiquer le périmètre exclusif auprès du store de checkpoint.
2. Lire une page source avec `fetch_page(mode, cursor, limit)`.
3. Valider la pagination et les clés, puis appliquer chaque mapping de façon
   idempotente dans la cible.
4. Après confirmation de toutes les applications, committer le checkpoint de
   la page avec la version attendue ; recommencer à l'étape 2 s'il reste une page.
5. En full avec `deactivate`, désactiver atomiquement les absents.
6. Enregistrer le dernier succès et le rapport complet.

Si le troisième élément d'une page échoue, les deux premiers peuvent déjà être
appliqués. **Le checkpoint reste celui de la page précédente.** Une reprise
rejoue la page ; la cible retourne `unchanged` pour un contenu déjà appliqué.
Tous ses effets doivent être idempotents, y compris les effets externes : un
adapter doit par exemple les coordonner via une outbox transactionnelle.

Le mode incrémental repart de `last_successful_cursor`. Le mode complet repart
toujours du début après un échec ou une annulation ; ses commits par page
conservent les métriques sans déplacer le curseur incrémental. Cette décision
évite de reprendre un full sync sans posséder les clés des pages antérieures.

En full, un ensemble de clés vues est borné par `max_full_items`. Un dépassement
interrompt la tentative avant la finalisation. Les éléments volontairement
ignorés par le mapper restent vus, ce qui évite de les désactiver. Un full vide
réussi avec `deactivate` désactive tous les éléments actifs du périmètre : la
source doit donc garantir une énumération complète, cohérente et autorisée.

`ignore` conserve les absents. `deactivate` appelle une opération cible atomique
uniquement après lecture et application de toutes les pages. Un échec avant
cette phase ne désactive rien. Une nouvelle observation réactive l'élément.
Le hard-delete est exclu.

## Job Et État De Synchronisation

`get_sync_status` retourne le `JobRecord[SyncRequest, SyncReport]` existant.
`JobContext.job_id` relie le rapport à l'exécution ; aucun second modèle de
statut n'est créé. La progression utilise `JobProgress(completed=...)` avec
`total=None` et `percent=None` lorsque le total est inconnu. Les pages sont
comptées dans le rapport.

Le `SyncCheckpoint` conserve séparément le périmètre, `source_version`, une
version CAS, `last_successful_cursor`, `last_success_at` en UTC et les métriques
de la dernière page/exécution validée. `last_success_at` n'avance qu'après la
réussite complète, y compris la finalisation. Les rapports courants ne servent
jamais de points de reprise.

Changer de source, de schéma ou de règles de mapping nécessite de changer
`source_version` et de prévoir explicitement une migration des données et du
checkpoint, ou un nouveau périmètre. Un checkpoint d'une autre version est
refusé ; cette V1 ne le réinitialise pas silencieusement.

La soumission déduplique une même clé et une même requête/politique Job. Une
requête ou un budget différent avec cette clé produit un conflit. Après un
échec, le contrat Job permet un retry explicite du même JobId. `max_attempts=1`
reste le défaut ; fournir un budget supérieur à `start_sync` avant de demander
un retry au runner. Aucun retry automatique n'est exécuté.

L'annulation est coopérative avant chaque page et avant la finalisation. Une
page en cours peut se terminer et être checkpointée avant l'arrêt. L'annulation
du propriétaire asyncio est collectée et propagée par le runner ; elle ne
constitue pas une garantie d'annulation d'une écriture distante déjà envoyée.

## Rapports Et Erreurs

`get_sync_report` est disponible après une première tentative, y compris après
échec partiel ou annulation et indépendamment de l'expiration du JobRecord.
Un job encore queued peut ne pas avoir de rapport. Le rapport comprend
`created`, `updated`, `unchanged`, `deactivated`, `skipped`, `failed`, `pages`,
`complete` et au maximum 20 codes d'erreur avec positions page/item.

Les compteurs décrivent **la dernière tentative**. Sur reprise, une application
déjà effectuée est comptée `unchanged`. `failed` compte aussi un échec de page,
de checkpoint ou de finalisation ; il ne dénombre pas les éléments non tentés.
Le moteur s'arrête au premier échec. `complete` indique la fin de la réconciliation,
tandis que le statut du job indique l'issue de son exécution/publication.

| Code | Interprétation |
|---|---|
| `source_failed`, `invalid_page` | Lecture ou contrat de pagination invalide |
| `missing_external_key`, `mapping_failed` | Identité absente ou mapping invalide/non implémenté |
| `target_failed` | Application cible refusée ou incertaine |
| `checkpoint_failed`, `execution_failed` | Persistance du checkpoint ou publication de l'état échouée |
| `finalization_failed` | Désactivation refusée ou incertaine |
| `run_limit` | Limite de pages ou de clés atteinte |
| `sync_busy`, `source_version_conflict` | Périmètre occupé ou checkpoint incompatible |
| `cancelled`, `interrupted` | Annulation coopérative ou interruption du propriétaire |

Une panne du stockage des rapports peut empêcher leur mise à jour ; elle remonte
au runner, sans fabriquer un rapport de succès. La séparation des commits cible,
checkpoint, rapport et JobRecord n'est pas une transaction distribuée. Après
une réponse de persistance incertaine, relire l'état et s'appuyer sur l'idempotence.

Ne stocker aucun secret dans les clés, curseurs, versions et payloads. Les objets
SDK, secrets Pydantic, champs masqués et payloads non JSON sont contrôlés avant
mapping/application. Chaque source/patch utilise la limite de 64 KiB et de 32
niveaux du contrat Job. Les valeurs sensibles en texte libre restent à exclure
par le projet ; les messages d'exception et les payloads ne sont pas copiés dans
les erreurs publiques. Instrumenter JobId, correlation ID technique, tentative,
pages, compteurs et durée via l'observabilité du projet.

## Exemple Python Avec Adapters Mémoire

Cet exemple volontairement local montre le contrat sans service externe :

```python
import asyncio
from pydantic import BaseModel
from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
from arclith.adapters.outbound.memory.synchronization import InMemorySyncCheckpoint, InMemorySyncTarget
from arclith.application.services.job_service import JobService
from arclith.application.services.synchronization import SyncJobHandler, SynchronizationService
from arclith.domain.models.synchronization import SourcePage, SyncDefinition, SyncMapping, SyncReport, SyncRequest
from arclith.domain.ports.outbound.synchronization import SyncMapper, SyncSourcePort


class CustomerSource(BaseModel):
    external_id: str
    name: str


class CustomerFields(BaseModel):
    name: str


class DemoSource(SyncSourcePort[CustomerSource]):
    async def fetch_page(self, *, mode, cursor, limit):
        if cursor == "watermark-v1":
            return SourcePage(items=(), checkpoint_cursor="watermark-v1")
        return SourcePage(
            items=(CustomerSource(external_id="customer-1", name="Alice"),),
            checkpoint_cursor="watermark-v1",
        )


class CustomerMapper(SyncMapper[CustomerSource, CustomerFields]):
    def map(self, source):
        return SyncMapping(value=CustomerFields(name=source.name), owned_fields=("name",))


async def main():
    definition = SyncDefinition(name="customers", external_key="external_id")
    checkpoints = InMemorySyncCheckpoint()
    target = InMemorySyncTarget(CustomerFields)
    handler = SyncJobHandler(
        definition, DemoSource(), target, CustomerMapper(), checkpoints,
        source_type=CustomerSource, target_type=CustomerFields,
    )
    store = InMemoryJobStore(SyncRequest, SyncReport)
    runner = InMemoryJobRunner(store, handler)
    service = SynchronizationService(definition, JobService(runner, store), checkpoints)

    job_id = await service.start_sync("incremental", idempotency_key="pull-1")
    assert await service.start_sync("incremental", idempotency_key="pull-1") == job_id
    await runner.run(job_id)
    report = await service.get_sync_report(job_id)
    assert report.complete and report.created == 1
    assert (await checkpoints.load("customers")).last_successful_cursor == "watermark-v1"

    next_job = await service.start_sync("incremental")
    await runner.run(next_job)
    assert (await service.get_sync_report(next_job)).created == 0


asyncio.run(main())
```

## Limites Et Adapters Durables

Les adapters mémoire sont **non durables**, réservés au développement/test sur
une boucle asyncio. Le store cible est borné à 100 000 records par défaut ; le
store de checkpoint conserve au maximum 1 000 rapports de jobs distincts. Ces
capacités sont configurables à la construction. `delete_report(job_id)` permet
une rétention explicite des rapports terminés, indépendante de la purge Job.
Un dépassement de capacité des rapports est refusé avant les effets cible.

Un adapter durable doit implémenter l'exclusivité du périmètre, le CAS, la
persistance des rapports, l'application idempotente et la finalisation atomique.
Une revendication n'expire pas implicitement dans cette V1 : une récupération
après crash doit vérifier/fencer l'ancien worker, y compris ses écritures cible,
avant de permettre une nouvelle exécution. La V1 ne fournit pas de recovery
distribué ni de lease automatique.

Pour une volumétrie dépassant la borne full, remplacer ultérieurement l'ensemble
par une session durable de marquage/sweep avec un contrat et des tests dédiés.
Push, bidirectionnel, résolution de conflits par champ, CDC, webhooks et scheduler
restent des extensions séparées. Aucun connecteur concret ni projection
FastAPI/MCP/RabbitMQ/LangGraph n'est créé par ce blueprint.
