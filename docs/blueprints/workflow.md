# Blueprint Workflow

Le blueprint `workflow` orchestre des étapes séquentielles typées, conserve leur
progression et reprend depuis le dernier checkpoint confirmé. Le domaine reste
indépendant du moteur d'exécution : les étapes métier et la projection du résultat
sont injectées derrière des ports. Cette V1 correspond à l'[issue #226](https://github.com/karned-rekipe/arclith/issues/226).

Les adapters mémoire fournis servent au développement et aux tests. **Ils ne
survivent pas à un redémarrage du processus.** La durabilité réelle nécessite
un adapter de `WorkflowStorePort` et une stratégie de reprise explicite.

## Choisir Le Bon Contrat

| Besoin | Contrat |
|---|---|
| Orchestration courte dans une transaction | Use case direct |
| Une unité de travail avec statut, annulation et retry | [Job](job.md) |
| Plusieurs étapes à confirmer et reprendre séparément | Workflow |
| Cycle de vie métier d'un agrégat | [State-machine](state-machine.md) |
| Réconciliation d'une source vers une cible | [Synchronization](synchronization.md), exécutée comme Job |

Un workflow possède son identité et son état d'exécution ; il ne remplace pas
le statut métier d'un document ou d'une commande. Il réutilise les compteurs
`JobProgress`, le `CancellationToken` et les règles de sérialisation de Job.
Ses statuts et checkpoints ont une sémantique propre : aucune super-classe de
processus ni dispatcher dynamique n'est nécessaire.

## Générer Une Feature

Utiliser les sources contenant les contrats Workflow. Les distributions
Arclith 0.31.0 / CLI 0.28.0 publiées avant cette évolution ne les contiennent pas.
La CLI vérifie le runtime avant toute écriture ; la [publication](../release.md)
des paquets est une étape distincte de la fusion du code.

Depuis le dépôt Arclith :

```bash
uv venv .venv-workflow-dev
uv pip install --python .venv-workflow-dev/bin/python -e . -e ./cli pytest pytest-asyncio
export PATH="$PWD/.venv-workflow-dev/bin:$PATH"
arclith-cli init publication-service
cd publication-service
cat > document-publication-workflow.yaml <<'YAML'
version: 1
context: DocumentPublicationContext
result: DocumentPublicationResult
steps:
  - name: validate_document
    max_attempts: 1
  - name: render_document
    max_attempts: 2
  - name: publish_document
    max_attempts: 1
  - name: notify_owner
    max_attempts: 2
YAML
arclith-cli add-blueprint workflow --feature document_publication \
  --no-entity --spec document-publication-workflow.yaml --dry-run
arclith-cli add-blueprint workflow --feature document_publication \
  --no-entity --spec document-publication-workflow.yaml
PYTHONPATH=src python -m pytest tests -q
```

La dernière commande utilise le même environnement local. Après une release
compatible, le projet peut utiliser son parcours habituel `uv sync --group dev`
puis `uv run pytest` avec les distributions publiées.

Pour rattacher une autre feature à une entité, la créer explicitement puis
choisir `--entity` à la place de `--no-entity` :

```bash
arclith-cli add-entity Document
arclith-cli add-blueprint workflow --entity Document \
  --feature document_review --spec document-publication-workflow.yaml
```

Cette cible ajoute une référence UUID sous forme de chaîne `entity_id` dans le
contexte initial. Les étapes vérifient l'existence et les autorisations ; le
modèle `Document` n'est pas réécrit. Workflow n'est pas un profil `add-entity`.

| Paramètre | Contrat V1 |
|---|---|
| `version` | Version de format YAML, entier 1 |
| `context`, `result` | Noms de classes publics distincts, 80 caractères maximum |
| `definition_version` | Entier 1 par défaut, maximum 1 000 000 ; version métier de la définition |
| `steps` | De 1 à 100 étapes ; noms publics uniques ; ordre conservé |
| `steps[].max_attempts` | Entier de 1 à 100, défaut 1, inclut la première tentative |

Les booléens ne remplacent pas les entiers. Le YAML est borné à 64 KiB ; les
champs inconnus, le code, les imports et les noms Python réservés sont refusés.
La recette V1 embarque les paramètres canoniques et leurs digests, sans chemin
vers le YAML original. Le manifeste de feature V3 réutilise les cibles
`standalone` et `entity` introduites par Job. Les anciennes recettes restent
compatibles ; aucune migration de format n'est requise.

## Fichiers Et Composition

La génération fournit :

- les modèles contexte/résultat dans `domain/models/<feature>_workflow.py` ;
- cinq ports inbound, commandes/requêtes, résultats et use cases : `start`,
  `get_status`, `cancel`, `resume`, `get_result` ;
- `application/workflows/<feature>/definition.py`, avec la définition ordonnée ;
- un module par étape dans `steps/`, avec un `WorkflowStep[Context]` explicite ;
- `context.py`, avec la projection pure `WorkflowResultMapper[Context, Result]` ;
- le container `build_<feature>_use_cases(runner, store)` et des tests avec fakes.

Les étapes et la projection de production lèvent `NotImplementedError` jusqu'à
leur implémentation. Les tests générés injectent leurs propres fakes : ils ne
prétendent pas publier un document ou notifier une personne.

Le propriétaire compose le runner avec la définition, **les étapes dans l'ordre
exact**, la projection et le store partagé avec les use cases. `start` persiste
une instance `pending` ; `await runner.run(id)` l'exécute. `resume` exécute
immédiatement la suite et doit également être attendu. Aucun scheduler ni tâche
en arrière-plan n'est lancé implicitement.

## Checkpoints Et Reprise

1. Le runner vérifie la définition et les schémas enregistrés, puis revendique
   l'exécution exclusive de l'instance.
2. Avant une étape, il contrôle l'annulation et persiste son début ainsi que
   le numéro de tentative.
3. Il transmet un snapshot isolé du contexte et un `StepExecutionContext`.
4. Après succès et validation du contexte retourné, le store confirme
   **atomiquement** le contexte, le succès de l'étape et le checkpoint.
5. Après toutes les étapes, la projection pure produit le résultat ; la
   completion et le résultat sont publiés ensemble.

Le checkpoint est le nombre d'étapes confirmées. Une étape confirmée n'est
jamais rejouée par `resume`. Une étape commencée mais non confirmée peut l'être :
la garantie autour de ses effets externes est **at-least-once**, sans transaction
distribuée ni exactly-once.

Chaque étape reçoit une `execution_key` dérivée de WorkflowId, du digest de
définition et de son nom. Elle reste identique entre tentatives. La transmettre
au système cible ou l'enregistrer dans la même transaction que l'effet métier.
Une simple variable mémoire ne protège pas les effets après un redémarrage.

Une erreur de persistance se propage au propriétaire, car son résultat peut être
incertain. Si un commit a réussi mais que sa réponse a été perdue, la reprise
relit le checkpoint et saute cette étape. Si aucun commit n'a eu lieu, elle
rejoue l'étape avec la même clé. Ne pas transformer une panne du store en succès
ou remettre arbitrairement le checkpoint à zéro.

Les tentatives sont comptées **avant l'appel de l'étape**, y compris si le
processus est interrompu ensuite. Par défaut `max_attempts=1` interdit tout retry
de cette étape. Un budget supérieur autorise un nombre borné de reprises
explicites ; aucun retry automatique, délai ni backoff n'est ajouté. Une fois
le budget épuisé, une intervention métier est nécessaire ; la V1 ne fournit
pas de réinitialisation ou migration silencieuse.

La projection du résultat est sans effet externe. Si elle échoue, toutes les
étapes restent confirmées ; `resume` peut réessayer cette projection pure sans
consommer une tentative métier ni rejouer les étapes.

## Statuts, Annulation Et Observation

| Niveau | États |
|---|---|
| Workflow | `pending`, `running`, `completed`, `failed`, `cancelled` |
| Étape | `pending`, `running`, `succeeded`, `failed` |

`get_result` refuse une instance non `completed`. `get_status` retourne le
contexte checkpointé, les étapes, compteurs de tentatives et erreurs à codes
fixes : `step_failed`, `step_not_implemented`, `execution_interrupted`,
`result_failed`. Les messages d'exception et payloads ne sont pas copiés dans
ces erreurs.

`progress` réutilise `JobProgress(completed=checkpoint, total=len(steps))`.
L'instance conserve les **200 derniers événements techniques** avec séquence,
type, étape et date UTC : début, reprise, étape commencée/confirmée, échec,
annulation et completion. C'est une observation bornée par lecture du store,
pas un journal d'audit durable ni un bus d'événements garanti. Le projet peut
instrumenter les ports avec ses adapters d'observabilité.

Annuler une instance `pending` l'arrête immédiatement. Pour une instance
`running`, la demande est vérifiée entre étapes : l'étape engagée peut terminer
et être checkpointée, mais aucune nouvelle étape n'est lancée. Une étape peut
aussi appeler `execution.cancellation.checkpoint()` à un point sûr. Une
annulation arrivée avant la publication finale empêche la completion.

Une instance `cancelled` ne reprend pas. Une étape non confirmée peut y conserver
son dernier état `running` : il indique une issue non confirmée, pas une tâche
encore planifiée. Une opération distante déjà envoyée n'est pas annulée
atomiquement. L'annulation de la tâche asyncio propriétaire est collectée,
enregistre `execution_interrupted` lorsque possible, puis propage `CancelledError`.

## Exemple Exécutable Sans Service Externe

Cet exemple simule une panne métier à la deuxième étape, puis démontre la
reprise sans répéter la première. Il utilise des fakes locaux explicites.

```python
import asyncio
from pydantic import BaseModel
from arclith.adapters.outbound.memory.workflow_runner import InMemoryWorkflowRunner
from arclith.adapters.outbound.memory.workflow_store import InMemoryWorkflowStore
from arclith.application.services.workflow_service import WorkflowService
from arclith.domain.models.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from arclith.domain.ports.outbound.workflow_runner import WorkflowStep, WorkflowResultMapper


class PublicationContext(BaseModel):
    document_ref: str
    completed: tuple[str, ...] = ()


class PublicationResult(BaseModel):
    document_ref: str


class DemoStep(WorkflowStep[PublicationContext]):
    def __init__(self, name, fail_once=False):
        self._name = name
        self.fail_once = fail_once
        self.keys = []

    @property
    def name(self):
        return self._name

    async def execute(self, context, *, execution):
        self.keys.append(execution.execution_key)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated failure")
        return PublicationContext(
            document_ref=context.document_ref,
            completed=(*context.completed, self.name),
        )


class DemoResult(WorkflowResultMapper[PublicationContext, PublicationResult]):
    def build_result(self, context):
        return PublicationResult(document_ref=context.document_ref)


async def main():
    definition = WorkflowDefinition(
        name="publication", version=1,
        context="PublicationContext", result="PublicationResult",
        steps=(WorkflowStepDefinition(name="validate"),
               WorkflowStepDefinition(name="publish", max_attempts=2)),
    )
    steps = [DemoStep("validate"), DemoStep("publish", fail_once=True)]
    store = InMemoryWorkflowStore(PublicationContext, PublicationResult)
    runner = InMemoryWorkflowRunner(
        definition, store, steps, DemoResult(),
        context_type=PublicationContext, result_type=PublicationResult,
    )
    service = WorkflowService(definition, runner, store)
    workflow_id = await service.start(
        PublicationContext(document_ref="document-42"), idempotency_key="publication-42"
    )
    failed = await runner.run(workflow_id)
    assert failed.status is WorkflowStatus.FAILED and failed.checkpoint == 1
    completed = await service.resume(workflow_id)
    assert completed.status is WorkflowStatus.COMPLETED and completed.checkpoint == 2
    assert len(steps[0].keys) == 1
    assert steps[1].keys[0] == steps[1].keys[1]
    assert (await service.get_result(workflow_id)).document_ref == "document-42"


asyncio.run(main())
```

## Version, Données Et Persistance Durable

L'instance conserve la définition entière, sa version et un digest SHA-256 de
la définition et des schémas Pydantic. Changer l'ordre, le budget, les noms ou les
schémas empêche une reprise incompatible. Les fonctions Python ne sont pas
inspectées pour deviner un changement métier : **incrémenter la version de
définition quand la sémantique d'une étape change** et garder l'ancienne
implémentation disponible pour les instances déjà démarrées.

Le contexte et le résultat réutilisent le contrat JSON de Job : modèle Pydantic
exact, champs JSON natifs, 64 KiB et 32 niveaux maximum chacun. Les SDK, objets
secrets Pydantic, valeurs non finies et secrets masqués par des serializers sont
refusés. Les champs de type chaîne peuvent néanmoins contenir des secrets : le
projet doit les exclure. Utiliser des références pour les fichiers et résultats
volumineux ; stocker les secrets dans le système prévu par le projet.

Le store mémoire conserve au maximum 1 000 instances par défaut, configurable
à la construction. `delete_terminal` supprime explicitement une instance
terminée sans propriétaire actif et sa clé d'idempotence. Cette suppression
autorise une nouvelle soumission avec la même clé ; aucune purge implicite
n'est exécutée.

Un adapter durable doit garantir :

- création atomique et idempotente, snapshots isolés et validation des payloads ;
- persistance atomique contexte/succès/checkpoint sous version attendue ;
- exclusivité de l'exécution et vérification du propriétaire à chaque mutation ;
- récupération après crash qui neutralise l'ancien propriétaire, y compris
  ses écritures externes, avant d'autoriser la reprise ;
- rétention explicite et conservation des anciennes définitions nécessaires.

La V1 n'expire ni ne vole automatiquement un verrou. La simple présence d'un
store distant ne suffit pas à rendre le runner durable. Un adapter vers un
moteur spécialisé pourra implémenter ces ports et sa planification sans changer
les étapes/use cases, à condition de préserver leurs contrats d'idempotence,
version, annulation et checkpoint. DAG parallèles, timers durables, attentes
humaines, compensation/saga et projections de transport restent hors scope.
