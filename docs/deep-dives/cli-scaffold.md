# Scaffold CLI Guidé

## Intention

`add-entity` et `add-usecase` accélèrent le démarrage du cœur métier sans
inventer le métier. Les fichiers générés sont de courts repères modifiables :

- ils indiquent où placer champs, invariants, commandes, queries et résultats ;
- ils gardent le domaine indépendant des frameworks et des adapters ;
- ils utilisent les vrais chemins d'import du package détecté ;
- ils renvoient vers des exemples complets au lieu de les recopier dans chaque
  projet.

Le scaffold ne génère ni endpoint FastAPI, ni tool FastMCP, ni graphe
LangGraph, ni mapping de base de données. Ces éléments viennent après le port
inbound et le use case.

## Commandes

Créer une entité guidée :

```bash
arclith-cli add-entity Todo
```

Créer un use case lié à une entité détectée :

```bash
arclith-cli add-usecase CreateTodo --entity Todo
```

Créer l'entité et le use case lié en une commande :

```bash
arclith-cli add-usecase CreateTodo --new-entity Todo
```

Créer un use case transverse :

```bash
arclith-cli add-usecase ImportCatalog --no-entity
```

Sans option, `add-usecase` propose les entités trouvées par analyse AST, puis
les choix « créer une nouvelle entité » et « transverse ». S'il n'existe aucune
entité, le wizard permet aussi d'annuler sans écriture. Pour les scripts, les
agents et la CI, toujours fournir l'une des trois options exclusives.

## Position Hexagonale

| Emplacement | Responsabilité | Exemples |
|---|---|---|
| `domain/models` | état et invariants métier | `Todo`, `TodoStatus` |
| `domain/ports/inbound` | contrat offert aux entrées | `CreateTodoCommand`, `CreateTodoPort` |
| `domain/ports/outbound` | besoin du cœur envers l'extérieur | `Repository[Todo]`, `TodoLookupPort` |
| `application/use_cases` | orchestration d'un objectif | `CreateTodoUseCase` |
| `adapters/inbound` | traduction HTTP, MCP, bus ou agent vers le port inbound | router, tool, handler, nœud |
| `adapters/outbound` | implémentation des dépendances externes | MongoDB, API distante, filesystem |

Un schéma de transport FastAPI ne devient pas automatiquement une commande du
domaine. L'adapter valide son contrat public puis construit le `Command` ou la
`Query` attendu par le port inbound.

## Choisir Command, Query Et Result

- Une `Command` demande une action ou une mutation : créer, terminer, importer.
- Une `Query` demande une lecture sans intention de mutation : lister,
  rechercher, consulter.
- Une entité peut être retournée directement lorsque c'est le résultat métier
  naturel d'une commande simple.
- Un `Result` Pydantic explicite est préférable pour une pagination, un bilan
  d'import ou une réponse composée.

Le template lié utilise `Command -> Entity` comme point de départ fréquent. Le
template transverse utilise `Command -> Result`. Les exemples suivants montrent
comment les adapter vers `Query` ou vers un autre résultat.

## Exemple 1 — CreateTodoUseCase

Le port inbound porte les données validées, sans dépendre du transport :

```python
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from todo_list_service.domain.models.todo import Todo


class CreateTodoCommand(BaseModel):
    title: str = Field(min_length=1, max_length=140)


class CreateTodoPort(ABC):
    @abstractmethod
    async def execute(self, command: CreateTodoCommand) -> Todo:
        raise NotImplementedError
```

Le use case orchestre la création et dépend du port repository générique :

```python
from arclith.domain.ports.outbound.repository import Repository

from todo_list_service.domain.models.todo import Todo
from todo_list_service.domain.ports.inbound.create_todo import (
    CreateTodoCommand,
    CreateTodoPort,
)


class CreateTodoUseCase(CreateTodoPort):
    def __init__(self, repository: Repository[Todo]) -> None:
        self._repository = repository

    async def execute(self, command: CreateTodoCommand) -> Todo:
        todo = Todo(title=command.title)
        return await self._repository.create(todo)
```

## Exemple 2 — ListTodosUseCase

Une lecture paginée mérite une `Query` et un `Result` explicites :

```python
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from todo_list_service.domain.models.todo import Todo


class ListTodosQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


class ListTodosResult(BaseModel):
    items: list[Todo]
    total: int = Field(ge=0)


class ListTodosPort(ABC):
    @abstractmethod
    async def execute(self, query: ListTodosQuery) -> ListTodosResult:
        raise NotImplementedError
```

```python
from arclith.domain.ports.outbound.repository import Repository

from todo_list_service.domain.models.todo import Todo
from todo_list_service.domain.ports.inbound.list_todos import (
    ListTodosPort,
    ListTodosQuery,
    ListTodosResult,
)


class ListTodosUseCase(ListTodosPort):
    def __init__(self, repository: Repository[Todo]) -> None:
        self._repository = repository

    async def execute(self, query: ListTodosQuery) -> ListTodosResult:
        offset = (query.page - 1) * query.per_page
        items, total = await self._repository.find_page(offset, query.per_page)
        return ListTodosResult(items=items, total=total)
```

## Exemple 3 — CompleteTodoUseCase

Une mutation charge l'entité, vérifie la version attendue, applique l'invariant
dans le domaine, puis délègue l'audit et l'incrément de version au
`UpdateUseCase` générique Arclith.

```python
from uuid6 import UUID

from pydantic import BaseModel


class CompleteTodoCommand(BaseModel):
    todo_id: UUID
    expected_version: int
```

```python
class CompleteTodoUseCase:
    def __init__(
        self,
        repository: Repository[Todo],
        updater: UpdateUseCase[Todo],
    ) -> None:
        self._repository = repository
        self._updater = updater

    async def execute(self, command: CompleteTodoCommand) -> Todo:
        todo = await self._repository.read(command.todo_id)
        if todo is None:
            raise TodoNotFound(command.todo_id)
        if todo.version != command.expected_version:
            raise TodoVersionConflict(command.todo_id)

        completed = todo.complete()
        return await self._updater.execute(completed)
```

`complete()` et les transitions autorisées appartiennent à `Todo`. La
conversion d'une exception en HTTP 404 ou 409 appartient à l'adapter FastAPI.
Le port `Repository[T]` partagé n'expose pas de compare-and-swap atomique entre
processus. Si cette garantie est requise, définir un port outbound métier et
une implémentation transactionnelle adaptée au store, sans gonfler le contrat
générique.

## Exemple 4 — ImportCatalogUseCase Transverse

Un import coordonne plusieurs éléments et n'a pas nécessairement une entité
principale. Il dépend de ports outbound décrivant ses besoins, pas d'un
`Repository[Any]` artificiel.

```python
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ImportCatalogCommand(BaseModel):
    source_uri: str


class ImportCatalogResult(BaseModel):
    imported: int = Field(ge=0)
    rejected: int = Field(ge=0)


class ImportCatalogPort(ABC):
    @abstractmethod
    async def execute(
        self,
        command: ImportCatalogCommand,
    ) -> ImportCatalogResult:
        raise NotImplementedError
```

```python
class ImportCatalogUseCase(ImportCatalogPort):
    def __init__(
        self,
        source: CatalogSourcePort,
        writer: CatalogWriterPort,
    ) -> None:
        self._source = source
        self._writer = writer

    async def execute(
        self,
        command: ImportCatalogCommand,
    ) -> ImportCatalogResult:
        records = await self._source.read(command.source_uri)
        outcome = await self._writer.write(records)
        return ImportCatalogResult(
            imported=outcome.imported,
            rejected=outcome.rejected,
        )
```

## Exemple 5 — FindByNameUseCase Et Port Outbound Spécifique

Ne pas ajouter `find_by_name`, `find_overdue` ou chaque requête métier au port
`Repository[T]` partagé. Lorsqu'une recherche exprime un besoin du domaine,
définir un petit port outbound dans le projet :

```python
from abc import ABC, abstractmethod

from todo_list_service.domain.models.todo import Todo


class TodoLookupPort(ABC):
    @abstractmethod
    async def find_by_name(self, normalized_name: str) -> list[Todo]:
        raise NotImplementedError
```

```python
class FindByNameUseCase:
    def __init__(self, lookup: TodoLookupPort) -> None:
        self._lookup = lookup

    async def execute(self, query: FindByNameQuery) -> FindByNameResult:
        normalized = query.name.strip().casefold()
        items = await self._lookup.find_by_name(normalized)
        return FindByNameResult(items=items)
```

L'adapter MongoDB, PostgreSQL ou distant implémente ensuite `TodoLookupPort`.
Le contrat générique `Repository[T]` reste stable et centré sur le cycle de vie
des entités.

## Tests Unitaires

Tester l'entité sans adapter pour prouver ses invariants :

```python
import pytest
from pydantic import ValidationError


def test_todo_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        Todo(title="   ")
```

Tester le use case avec un fake ou l'adapter memory :

```python
import pytest
from arclith.adapters.outbound.memory.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_create_todo_persists_entity() -> None:
    repository = InMemoryRepository[Todo]()
    use_case = CreateTodoUseCase(repository)

    created = await use_case.execute(CreateTodoCommand(title="Documenter"))

    assert await repository.read(created.uuid) == created
```

Pour un port outbound spécifique, un fake minimal rend le test plus lisible
qu'un mock d'un SDK MongoDB ou HTTP.

## Validation Du Scaffold

Dans le dépôt Arclith :

```bash
cd cli
uv run pytest tests/test_core_scaffold.py tests/test_scaffold_cli.py -q
cd ..
make quality
make docs
```

Dans le projet généré, compiler les fichiers puis écrire les tests métier avant
de brancher les adapters :

```bash
uv run python -m compileall -q src
uv run pytest -q
```

## Troubleshooting

### Entité introuvable

`--entity Todo` ne se fie pas au seul nom de fichier. Le scanner AST doit
trouver une classe `Todo` qui hérite directement de `Entity`. Corriger la
classe ou utiliser `--new-entity Todo` si le fichier n'existe pas.

### Fichier homonyme incompatible

`--new-entity Todo` refuse d'écraser `domain/models/todo.py` si ce fichier ne
déclare pas l'entité attendue. Renommer ou corriger manuellement le fichier,
puis relancer la commande.

### Use case sans entité principale

Utiliser `--no-entity`. Le résultat ne contient pas de `Repository[T]` injecté ;
ajouter seulement les ports outbound réellement nécessaires à l'orchestration.

## Suite

- [Créer une entité Todo](../tutorials/todo-list/02-create-entity.md)
- [Créer les use cases Todo](../tutorials/todo-list/03-create-usecase.md)
- [Architecture Arclith](https://github.com/karned-rekipe/arclith/blob/main/arclith/docs/architecture.md)
- [Décisions Arclith](../decisions.md)
