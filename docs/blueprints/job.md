# Blueprint Job

Le blueprint `job` initialise une unité de travail identifiable dont l'exécution
peut être suivie et contrôlée. Il fournit une requête et un résultat typés, les
opérations `submit`, `get_status`, `cancel`, `retry`, `get_result`, un handler
métier à compléter et des tests avec un fake déterministe.

Cette capacité est développée dans l'[issue #224](https://github.com/karned-rekipe/arclith/issues/224).
Elle nécessite les sources contenant ce blueprint ; les distributions Arclith
0.31.0 / CLI 0.28.0 ne le contiennent pas. La publication PyPI se vérifie
séparément selon le [processus de release](../release.md).

## Choisir Ce Modèle

| Besoin | Modèle adapté |
|---|---|
| Réponse immédiate sans état d'exécution à conserver | Use case synchrone/asynchrone directement attendu |
| Travail soumis, identifiable, à suivre ou annuler | Job |
| Traitement d'une collection de données | Batch, éventuellement exécuté comme job |
| Plusieurs étapes avec checkpoints et reprise | Workflow, hors de cette V1 |
| Cycle de vie métier d'une facture | [State-machine](state-machine.md) |

Un job n'est ni un broker ni une entité métier. `job` s'ajoute avec
`add-blueprint`, pas avec `add-entity --profile job`. Ses opérations ne créent
aucun endpoint FastAPI, tool FastMCP, binding RabbitMQ ni node LangGraph.

## Générer Une Feature Sans Entité

Depuis un checkout contenant ce blueprint, installer les sources dans un
environnement de développement, puis utiliser la CLI de cet environnement :

```bash
# Dans le dépôt Arclith :
uv venv .venv-job-dev
uv pip install --python .venv-job-dev/bin/python -e . -e ./cli pytest pytest-asyncio
export PATH="$PWD/.venv-job-dev/bin:$PATH"

# Depuis un répertoire de travail :
arclith-cli init report-service
cd report-service
cat > report-job.yaml <<'YAML'
version: 1
request: GenerateReportRequest
result: GenerateReportResult
cancellable: true
max_attempts: 2
retention_days: 7
YAML

arclith-cli blueprints --json
arclith-cli add-blueprint job --feature report_generation \
  --no-entity --spec report-job.yaml --dry-run
arclith-cli add-blueprint job --feature report_generation \
  --no-entity --spec report-job.yaml
PYTHONPATH=src python -m pytest tests -q
```

La dernière commande utilise le Python du même environnement, avec le framework
local. Après publication d'une version compatible, le parcours habituel
`uv sync --group dev` / `uv run pytest` s'applique au projet consommateur.

`--entity` et `--no-entity` sont mutuellement exclusifs ; l'un des deux est
obligatoire. `--feature` est obligatoire avec `--no-entity`. Les noms request et
result doivent être des noms de classes Python publics distincts, commençant
par une majuscule. Les imports arbitraires et paramètres inconnus sont refusés.
`cancellable` doit être un booléen ; `max_attempts` un entier de 1 à 100 et
`retention_days` un entier de 1 à 3650. Le fichier YAML déclare les six champs,
y compris `version: 1`. Au niveau Python, `max_attempts=1` est le défaut.

## Lier Le Job À Une Entité

```bash
arclith-cli add-entity Document
arclith-cli add-blueprint job --entity Document \
  --feature document_analysis --spec report-job.yaml
```

Le modèle `Document` doit exister. La requête générée porte `entity_id`, un UUID
validé puis normalisé en chaîne JSON. Le job possède son propre `JobId` et son
propre statut. Il ne modifie ni le schéma ni l'état du document. Le handler
reste responsable de l'existence du document, des droits et des effets métier.
La cible peut également référencer un `ImmutableRecord` existant sans le modifier.

## Fichiers Et Composition

Les fichiers suivent le layout `src/<package>/` :

```text
domain/models/report_generation_job.py       # request/result à compléter
domain/ports/inbound/submit_report_generation.py
domain/ports/inbound/get_status_report_generation.py
domain/ports/inbound/cancel_report_generation.py
domain/ports/inbound/retry_report_generation.py
domain/ports/inbound/get_result_report_generation.py
application/jobs/report_generation.py        # handler métier explicite
application/use_cases/…                      # cinq use cases typés
infrastructure/containers/report_generation.py
tests/application/test_report_generation_job.py
docs/blueprints/report_generation-job.md
.arclith/features/report_generation.yaml
```

Les exceptions sont réutilisées depuis `arclith.domain.errors.job`, sans créer
cinq variantes métier identiques. Le container reçoit un `JobRunnerPort` et le
`JobStorePort` utilisé par ce runner ; les requêtes de statut/résultat doivent
lire le même store. La logique applicative ne dépend d'aucun adapter concret.

Le handler initial lève `NotImplementedError`. Les tests fournissent un fake
explicite et vérifient aussi que ce point d'extension ne prétend pas effectuer
un travail métier. Après ajout de champs obligatoires, enrichir leurs fixtures
avec des exemples représentatifs du projet.

## Exécuter Et Observer En Python

Cet exemple complet utilise directement les primitives du framework :

```python
import asyncio

from pydantic import BaseModel

from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
from arclith.application.services.job_service import JobService
from arclith.domain.models.job import JobProgress, JobRequest
from arclith.domain.ports.outbound.job_runner import JobContext, JobHandler


class SumRequest(BaseModel):
    values: list[int]


class SumResult(BaseModel):
    total: int


class SumHandler(JobHandler[SumRequest, SumResult]):
    async def execute(self, request: SumRequest, context: JobContext) -> SumResult:
        await context.cancellation.checkpoint()
        result = SumResult(total=sum(request.values))
        await context.report_progress(JobProgress(percent=100))
        return result


async def main() -> None:
    store = InMemoryJobStore(SumRequest, SumResult)
    runner = InMemoryJobRunner(store, SumHandler())
    service = JobService(runner, store)
    request = JobRequest(payload=SumRequest(values=[1, 2, 3]), idempotency_key="sum-001")
    job_id = await service.submit(request)
    assert await service.submit(request) == job_id
    assert (await service.get_status(job_id)).status == "queued"
    await runner.run(job_id)
    assert (await service.get_result(job_id)).payload.total == 6


asyncio.run(main())
```

`submit` enregistre un job `queued` ; il ne crée aucune tâche en arrière-plan.
`await runner.run(job_id)` réclame atomiquement puis exécute une tentative.
Si l'application place cet appel dans une tâche asyncio pour observer/annuler
le job en parallèle, elle doit posséder et attendre cette tâche, y compris lors
de l'arrêt. Deux appels concurrents à `run` n'exécutent pas deux fois la même
tentative : le second reçoit une erreur de transition ou de version.

## Cycle De Vie, Annulation Et Retry

```text
submit → queued → running → succeeded
             │        ├──→ failed ── retry explicite ──→ queued (attempt + 1)
             │        └──→ cancelled après reconnaissance coopérative
             └───────────→ cancelled immédiatement
```

| Opération | Précondition | Effet |
|---|---|---|
| `submit` | Requête et politique valides | Nouveau JobId UUIDv7 ou job idempotent existant |
| `run` (adapter mémoire) | `queued` | Démarre une tentative, puis publie son issue |
| `cancel` | Annulable, `queued` | `cancelled`, sans appel au handler |
| `cancel` | Annulable, `running` | Positionne `cancellation_requested` |
| `retry` | `failed`, `attempt < max_attempts` | Même JobId, tentative suivante en `queued` |
| `get_result` | `succeeded` | Enveloppe `JobResult[T]` V1 |

Le token se consulte avec `await context.cancellation.is_requested()` ;
`await context.cancellation.checkpoint()` lève `JobCancellationRequested` que
le runner convertit en `cancelled`. Les checkpoints doivent se trouver à des
points où une interruption est acceptable. Un handler qui termine avant de
reconnaître la demande peut réussir. Un calcul bloquant ne peut pas être tué
de manière sûre par ce mécanisme. Une annulation déjà acquise est idempotente.

Un retry remet à zéro progression, erreur courante, dates de la tentative et
demande d'annulation. Il conserve l'identité, la requête et l'historique minimal
des tentatives terminées. Le résultat n'est disponible qu'après succès. Aucun
retry n'est automatique, même si `max_attempts` est supérieur à 1.

Chaque mutation effective incrémente `version`. Le store accepte uniquement les
changements typés de `arclith.domain.services.job_lifecycle`, avec une version
attendue ; aucun `save(record)` arbitraire n'est exposé. Horodatages UTC, ordre
temporel, historique et cohérence statut/résultat/erreur sont validés.

## Idempotence, Données Et Erreurs

L'unicité d'une clé s'applique à **une instance de store et une définition de
job**. Même clé et même requête canonique renvoient le job existant, quel que
soit son statut, sans le relancer. Changer le payload ou la politique avec la
même clé lève `JobIdempotencyConflict`. Sans clé, chaque soumission crée un job.
Ne pas partager un store entre définitions différentes.

Les valeurs sont copiées à l'entrée et à la sortie. Le calcul canonique lit les
champs déclarés, y compris ceux exclus de la sérialisation de présentation ;
aliases et serializers Pydantic ne peuvent pas masquer une différence de requête.
La politique est incluse dans l'empreinte. Les payloads doivent correspondre
exactement aux classes request/result déclarées au store.

Requêtes et résultats acceptent des valeurs JSON natives et modèles Pydantic
imbriqués. Ils sont limités à 64 KiB et 32 niveaux de profondeur ; l'enveloppe
de soumission compte dans cette limite. Les flottants non finis, objets SDK et
objets `SecretStr`/`SecretBytes` sont refusés. Sérialiser explicitement dates et
UUID métier en chaînes. Les gros résultats passent par une référence vers du
storage ; les credentials passent par des ports injectés, jamais par le job.
La limite technique ne détecte pas un secret placé dans une chaîne ordinaire :
le projet doit exclure les champs sensibles de ses contrats.

La progression optionnelle utilise `JobProgress(percent=…)`, nombre fini entre
0 et 100, ou `JobProgress(completed=…, total=…)`, avec des compteurs entiers
de 0 à 10¹². `total=None` indique un total inconnu et n'invente aucun pourcentage ;
un total fourni doit être supérieur ou égal à `completed`. Au moins un pourcentage
ou un compteur completed est requis. La progression ne contient ni logs ni payload
métier. Le contexte mémoire expose aussi `job_id` pour rattacher un rapport externe
à l'exécution, comme le fait [synchronization](synchronization.md).
`JobError` est versionné
et expose trois codes fixes : `handler_failed`, `handler_not_implemented`,
`execution_interrupted`, avec une propriété `message` stable. Le texte brut et
la trace d'une exception ne sont jamais copiés dans le record public.

Erreurs applicatives : `JobNotFound`, `JobResultUnavailable`,
`JobTransitionError`, `JobVersionConflict`, `JobIdempotencyConflict`.
Instrumenter le handler et son propriétaire avec JobId, correlation ID,
attempt, durée et statut. Réserver les traces techniques au système
d'observabilité et ne pas journaliser les payloads.

## Rétention Et Limites Mémoire

**Le store et le runner mémoire sont non durables et réservés au développement
et aux tests.** Ils coordonnent les coroutines d'une même boucle asyncio ; ils
ne coordonnent ni processus, ni machines, ni boucles distinctes. Un arrêt du
processus perd les jobs et leurs clés d'idempotence. Les calculs CPU bloquants
bloquent la boucle : utiliser un adapter d'exécution approprié.

La rétention part de la fin de la dernière tentative. Le nettoyage est une
action explicite `await store.purge_expired()` ; aucun timer/cron n'est créé.
Il retire les jobs terminés ayant atteint l'échéance ainsi que leurs clés. Les
jobs actifs sont conservés. Après purge, une clé peut créer un nouveau job :
c'est la limite de la fenêtre d'idempotence. Un job failed purgé ne peut plus
être retenté par son ancien identifiant.

L'annulation de la tâche propriétaire de `run` enregistre `execution_interrupted`
puis propage `asyncio.CancelledError`, tant que le store reste disponible et
que le processus permet d'effectuer ce nettoyage. Ce n'est pas une garantie de
récupération après arrêt brutal. Les erreurs de persistance doivent être
traitées par le propriétaire, sans supposer que le travail n'a pas été exécuté.

## Manifestes, Recettes Et Évolution

`job` écrit un manifeste **V3** :

```yaml
version: 3
feature: report_generation
blueprint:
  name: job
  version: 1
target:
  kind: standalone
# parameters, digests et operations sont également obligatoires.
```

Pour une entité, `target` contient `kind: entity` et `entity: {name, module}`.
Les formats V1 CRUD/append-only et V2 state-machine sont conservés. La recette
garde son enveloppe V1 et versionne les arguments de cible de `job` avec
`target_version: 1`, puis `entity` ou `no_entity: true`. Elle embarque les
paramètres canoniques et leurs empreintes ; le fichier spec original n'est
plus nécessaire au replay.

Une recette state-machine enregistrée avec CLI 0.28.0 garde son empreinte et
produit les mêmes fichiers octet pour octet. Une migration limitée à une
empreinte de sources auditée neutralise l'ajout de `job` au catalogue, sans
désactiver les vérifications de dérive des renderers.

Dry-run sans écriture, collisions avant installation, compensation d'une
écriture interrompue et préservation du code personnalisé utilisent le plan
commun. Une configuration différente pour une feature déjà installée est
refusée. Le replay restaure le scaffold, pas les personnalisations métier :
conserver ces dernières dans Git. Voir les [recettes CLI](../cli-recipe.md).

## Ajouter Un Adapter De Production

Implémenter `JobStorePort[RequestT, ResultT]` avec soumission/idempotence
atomique, transitions contrôlées et contrôle de version. Implémenter
`JobRunnerPort[RequestT, ResultT]` pour le moteur choisi, puis réinjecter les
ports dans le container généré. Les cinq use cases et les modèles métier
restent indépendants du fournisseur.

Avant mise en production, tester coordination, durabilité, propriété des
workers, récupération des tentatives interrompues, rétention et sécurité des
données. Des adapters RabbitMQ/Celery/Kubernetes/Temporal pourront fournir ces
garanties ; aucun n'est fourni par cette V1. Prévoir l'idempotence des effets
métier : le contrat mémoire ne promet pas d'exécution distribuée exactly-once.
