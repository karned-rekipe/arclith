# Blueprint State-machine

Le blueprint `state-machine` génère un cycle de vie métier typé à partir d'une
spécification YAML. Il généralise la mécanique stable — états, transitions,
erreurs, chargement et compare-and-swap — sans inventer les préconditions ou les
effets de bord propres au projet.

Utiliser ce blueprint lorsqu'un agrégat évolue par verbes métier, par exemple
`submit`, `approve` ou `reject`, et qu'un `update(status=...)` générique
contournerait ses invariants. Une facture, une commande ou un dossier de
validation sont de bons candidats.

## Ce Que Le Blueprint N'est Pas

| Besoin | Modèle adapté |
|---|---|
| Modifier librement les champs d'une ressource | CRUD |
| Enregistrer des faits sans jamais réécrire le passé | Append-only |
| Faire évoluer l'état métier d'un agrégat par verbes autorisés | State-machine |
| Suivre l'exécution durable de plusieurs étapes | Workflow, hors de cette V1 |

La machine générée n'est pas un moteur dynamique. Le domaine n'expose pas
`transition("approved")` ni un setter public du statut. Une transition nommée
`approve` produit une méthode `approve`, un port `ApproveInvoicePort` et un use
case `ApproveInvoiceUseCase` que le typage, les tests et les futurs adapters
peuvent identifier directement.

Elle ne publie aucun événement, n'installe aucun broker, ne crée aucune route
FastAPI, aucun tool FastMCP et aucun node LangGraph. Ces projections restent des
décisions séparées.

## Écrire La Spec V1

Créer `invoice-lifecycle.yaml` :

```yaml
version: 1
state_field: status
initial_state: draft
states:
  - draft
  - submitted
  - approved
  - rejected
transitions:
  - name: submit
    from: [draft]
    to: submitted
  - name: approve
    from: [submitted]
    to: approved
  - name: reject
    from: [submitted]
    to: rejected
```

Les noms sont des identifiants Python publics. Les états, transitions et sources
doivent être uniques. L'état initial, chaque source et chaque cible doivent être
déclarés dans `states`. La CLI refuse aussi un état inaccessible depuis
`initial_state` : un état orphelin est généralement une erreur de spec, et non un
warning à ignorer dans du code généré.

La CLI trie canoniquement les états, les sources et les transitions avant de
calculer les digests et de générer les fichiers. Deux specs qui ne diffèrent que
par l'ordre de leurs listes produisent donc la même configuration résolue.

Les champs techniques d'`Entity`, notamment `uuid`, `version`, les champs
d'audit et de soft-delete, ainsi que les attributs protégés Pydantic `model_*`,
ne peuvent pas devenir `state_field`. Un mot-clé Python, un nom privé, une
transition dupliquée, une cible inconnue ou un état inaccessible arrête tout le
plan avant la première écriture.

## Créer L'entité Et Le Cycle De Vie Ensemble

Le parcours le plus direct est atomique du point de vue de la commande : la spec
est entièrement validée et toutes les collisions sont prévalidées avant la
création du modèle.

```bash
arclith-cli init invoice-service
cd invoice-service

arclith-cli add-entity Invoice \
  --profile state-machine \
  --spec invoice-lifecycle.yaml
```

Le modèle créé contient le champ typé et protégé :

```python
from collections.abc import Mapping
from typing import Any, Self

from pydantic import ConfigDict, Field

from arclith.domain.models.entity import Entity
from invoice_service.domain.models.invoice_state import InvoiceState


class Invoice(Entity):
    model_config = ConfigDict(validate_assignment=True)

    status: InvoiceState = Field(
        default=InvoiceState.DRAFT,
        frozen=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is not None and "status" in update:
            raise ValueError("status changes must use the generated lifecycle")
        return super().model_copy(update=update, deep=deep)

    def _copy_with_status(self, target: InvoiceState) -> Self:
        return super().model_copy(update={"status": target})
```

`validate_assignment=True` et `Field(frozen=True)` empêchent
`invoice.status = ...`. La surcharge de `model_copy` refuse aussi une mise à jour
générique du champ ; seul le service de cycle de vie appelle la méthode privée de
copie contrôlée. Les primitives Pydantic de bas niveau appelées directement sur
la classe de base, comme `BaseModel.model_construct`, restent hors du contrat
métier. Le modèle reste une `Entity` Arclith et conserve son UUIDv7, son audit,
son soft-delete et sa version optimiste.

Ajouter ensuite les autres champs et invariants métier dans `Invoice`. Ne pas
remplacer le champ protégé par un `str` libre ni ajouter un setter générique.

## Appliquer Le Blueprint À Une Entité Existante

La V1 ne patche jamais silencieusement un fichier métier existant. Préparer le
champ, puis appliquer le blueprint :

```python
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field

from arclith.domain.models.entity import Entity


class Invoice(Entity):
    model_config = ConfigDict(validate_assignment=True)

    status: Literal["draft", "submitted", "approved", "rejected"] = Field(
        default="draft",
        frozen=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is not None and "status" in update:
            raise ValueError("status changes must use the generated lifecycle")
        return super().model_copy(update=update, deep=deep)

    def _copy_with_status(self, target: str) -> Self:
        return super().model_copy(update={"status": target})
```

```bash
arclith-cli add-blueprint state-machine \
  --entity Invoice \
  --feature invoice_lifecycle \
  --spec invoice-lifecycle.yaml \
  --dry-run

arclith-cli add-blueprint state-machine \
  --entity Invoice \
  --feature invoice_lifecycle \
  --spec invoice-lifecycle.yaml
```

Le type accepté est un `Literal[...]` contenant exactement les états déclarés,
ou un enum `InvoiceState` dont la déclaration locale/importée expose exactement
les valeurs persistées de la spec. Le champ doit rejeter l'affectation et la
copie générique : utiliser un modèle entièrement frozen, ou
`ConfigDict(validate_assignment=True)` avec `Field(..., frozen=True)`, surcharger
`model_copy` et fournir la méthode privée montrée ci-dessus. Si le champ manque,
a un type incompatible ou reste contournable, la CLI explique la modification
requise et ne touche à aucun fichier.

## Structure Générée

Pour la feature `invoice_lifecycle`, la V1 produit des fichiers légers et séparés :

```text
src/invoice_service/
├── domain/
│   ├── models/invoice_state.py
│   ├── services/invoice_lifecycle.py
│   ├── errors/invoice_lifecycle.py
│   └── ports/
│       ├── inbound/
│       │   ├── submit_invoice.py
│       │   ├── approve_invoice.py
│       │   └── reject_invoice.py
│       └── outbound/invoice_lifecycle.py
├── application/use_cases/
│   ├── submit_invoice.py
│   ├── approve_invoice.py
│   └── reject_invoice.py
└── infrastructure/containers/invoice_lifecycle.py
tests/
├── domain/test_invoice_lifecycle.py
└── application/test_invoice_lifecycle_use_cases.py
docs/blueprints/invoice_lifecycle-state-machine.md
```

Chaque transition a son erreur spécialisée, par exemple
`ApproveInvoiceNotAllowedError`. `InvoiceNotFoundError`,
`InvoiceVersionConflictError` et `InvoiceTransitionNotAllowedError` restent
distinctes : une absence, une course de concurrence et un refus métier ne sont
pas le même diagnostic.

## Gardes Et Préconditions Métier

Le service généré vérifie toujours l'état source avant toute précondition :

```python
from enum import Enum


class InvoiceLifecycle:
    def approve(self, entity: Invoice) -> Invoice:
        raw_current = entity.status
        current_value = (
            raw_current.value if isinstance(raw_current, Enum) else raw_current
        )
        current = InvoiceState(current_value)
        if current not in frozenset((InvoiceState.SUBMITTED,)):
            raise ApproveInvoiceNotAllowedError(current.value)
        self._ensure_approve_preconditions(entity)
        target = type(raw_current)(InvoiceState.APPROVED.value)
        return entity._copy_with_status(target)

    def _ensure_approve_preconditions(self, entity: Invoice) -> None:
        """Add project-owned guards here; the state guard already ran."""
        return None
```

La spec V1 ne prétend pas connaître une limite de crédit, une signature requise
ou le rôle de l'acteur. Ajouter ces contrôles dans le hook nommé, ou injecter une
politique métier explicite si le contrôle dépend d'un port. Ne jamais déplacer
le contrôle d'état dans un router ou un handler de transport : tous les appels
au cœur applicatif doivent obtenir le même résultat.

Le service retourne une copie via `_copy_with_status`. Si une garde échoue,
l'objet chargé reste dans son état d'origine et le port de persistance n'est pas
appelé.

## Concurrence Et Compare-and-swap

Le use case suit quatre étapes :

1. charger l'agrégat par son UUID ;
2. comparer sa version à `expected_version` ;
3. appliquer le verbe métier au moyen du service de domaine ;
4. appeler `compare_and_swap(candidate, expected_version=...)`.

Le port outbound généré exige que l'adapter fasse atomiquement la comparaison,
la persistance, l'incrément de version et la mise à jour de l'audit. La
comparaison effectuée juste après le chargement améliore le diagnostic et évite
un travail inutile, mais elle ne protège pas contre une autre écriture entre la
lecture et la persistance.

Un adapter SQL utilisera typiquement un `UPDATE ... WHERE uuid = ? AND version = ?`
et vérifiera qu'une ligne a été modifiée. Un adapter documentaire utilisera
l'équivalent natif de ce filtre/version. Une implémentation qui fait seulement
`read`, puis `update` sans condition atomique ne respecte pas le port.

Arclith ne génère pas d'adapter de production dans cette V1. Le container demande
explicitement une implémentation de `InvoiceLifecycleStore` au projet.

## Matrice De Tests

Le test domaine généré énumère le produit cartésien de tous les états et de
toutes les transitions. Pour chaque paire :

- une source autorisée doit produire exactement la cible déclarée ;
- une source interdite doit lever l'erreur spécialisée ;
- l'agrégat reçu doit rester inchangé.

Les tests applicatifs distinguent not-found, conflit de version et transition
interdite. Ils vérifient aussi qu'aucune écriture n'a lieu après une erreur et
qu'un CAS réussi incrémente la version.

Les fixtures générées utilisent `model_construct` uniquement pour isoler la
matrice de cycle de vie sans inventer de valeurs pour les champs métier requis
d'une entité existante. Les tests de gardes propres au projet doivent, eux,
construire des instances validées avec des valeurs métier représentatives.

Après génération :

```bash
uv sync
uv run pytest tests/domain tests/application -q
```

Remplacer ou compléter le faux store de test par les tests de contrat de votre
adapter. La matrice générée est un socle ; les gardes métier ajoutées par le
projet doivent recevoir leurs propres scénarios.

## Manifeste V2 Et Replay

Une feature paramétrée écrit `.arclith/features/invoice_lifecycle.yaml` :

```yaml
version: 2
feature: invoice_lifecycle
entity:
  name: Invoice
  module: invoice_service.domain.models.invoice
blueprint:
  name: state-machine
  version: 1
parameters:
  state_field: status
  initial_state: draft
  states: [approved, draft, rejected, submitted]
  transitions:
    - name: approve
      from: [submitted]
      to: approved
    - name: reject
      from: [submitted]
      to: rejected
    - name: submit
      from: [draft]
      to: submitted
digests:
  template: sha256:<64 caractères hexadécimaux>
  parameters: sha256:<64 caractères hexadécimaux>
operations:
  - approve
  - reject
  - submit
```

`parameters` contient uniquement des valeurs JSON/YAML sûres. Le digest
`template` détecte une évolution du renderer et versionne aussi le contrat de
validation appliqué aux entités existantes ; le digest `parameters` identifie la
configuration résolue. Une nouvelle spec incompatible avec un manifeste installé
est refusée au lieu de réécrire les fichiers du développeur.

`arclith.recipe.yaml` enregistre le même mapping canonique. Il n'enregistre pas
le chemin de `invoice-lifecycle.yaml` : le replay reste portable si le fichier
source a été déplacé ou supprimé. Avant toute écriture, le replay compare les
deux digests obligatoires au renderer, au contrat de validation et aux paramètres
courants ; une métadonnée absente ou une dérive est refusée explicitement. Les
recettes non paramétrées historiques restent tolérantes à l'absence de ces
métadonnées, et les manifests V1 restent lus sans conversion vers V2.

## Faire Évoluer Une Machine En Production

Ajouter un état ou une transition change un contrat persistant. Avant de
modifier la spec d'une feature déjà installée :

1. inventorier les valeurs stockées dans tous les environnements ;
2. décider comment les anciennes valeurs restent lisibles ;
3. écrire une migration explicite et réversible si nécessaire ;
4. versionner les consommateurs de messages ou d'API concernés ;
5. installer une nouvelle feature ou résoudre explicitement le manifeste.

Ne jamais renommer ou supprimer un état en comptant sur une régénération
silencieuse. Le blueprint préserve volontairement le code et refuse le drift ;
Git et la stratégie de migration du projet restent les sources de vérité pour
cette évolution.

## Formulation Prête Pour Un Agent

```text
Dans ce projet Arclith, crée une spec state-machine V1 pour Invoice avec les
états draft, submitted, approved et rejected. Génère Invoice avec
`arclith-cli add-entity Invoice --profile state-machine --spec <spec>`.
N'ajoute aucun transport. Implémente mes gardes métier uniquement dans les hooks
nommés, fournis un adapter qui respecte réellement le compare-and-swap, puis
exécute la matrice domaine et les tests applicatifs générés. Ne modifie pas
silencieusement le manifeste ou un fichier déjà personnalisé.
```

Cette formulation laisse au projet ses règles métier et son choix de
persistance, tout en conservant les invariants techniques du blueprint.
