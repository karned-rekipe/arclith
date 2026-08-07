# Architecture

arclith suit les principes de l'**architecture hexagonale** (Ports & Adapters) combinés à la **Clean Architecture**.

La règle fondamentale : les dépendances ne vont que vers l'intérieur.

```text
src/<package>/adapters + src/<package>/infrastructure
        ↓
   src/<package>/application
        ↓
     src/<package>/domain
```

---

## Layout canonique

Le layout recommandé est namespacé dans `src/<package>/...`.

```text
src/<package>/
  domain/
    models/
    ports/
      inbound/
      outbound/
  application/
    use_cases/
    services/
  adapters/
    inbound/
    outbound/
  infrastructure/
config/
tests/
main.py
```

Le framework expose cette convention avec `canonical_project_layout(package_name)`. Le sample officiel `_sample` l'applique sous `src/arclith_sample/`.

La convention canonique est `inbound` / `outbound`; les anciens noms `input` et `output`
ne sont pas supportés dans cette refonte pré-1.0:

- `inbound`: ce qui entre dans l'application et déclenche un cas d'usage (HTTP, MCP, CLI, jobs);
- `outbound`: ce que le coeur appelle vers l'extérieur (repositories, LLM, event bus, mail, cache).

---

## `src/<package>/domain/`

Le cœur métier. Aucune dépendance externe, aucun I/O.

### `domain/models/`

Les entités métier. Elles héritent de `Entity` (uuid, timestamps, soft-delete).

```python
@dataclass
class Ingredient(Entity):
    name: str = ""
    unit: str | None = None
```

### `domain/ports/inbound/`

Les ports offerts par le cœur. Ils décrivent les capacités appelables par les adapters entrants
sans exposer FastAPI, FastMCP, LangGraph, Pydantic AI ou un autre framework.

Exemples:

- `CreateIngredientPort`
- `ChatAgentPort`
- `RunWorkflowPort`

### `domain/ports/outbound/`

Les interfaces que le cœur consomme pour parler au monde extérieur.

- `Repository[T]` — contrat de persistance (create, read, update, delete, find_all…)
- `Logger` — contrat de logging

> C'est ici que tu définis aussi tes ports spécifiques (ex: `IngredientRepository` avec `find_by_name`,
> `LLMPort`, `EventPublisherPort`, `SecretResolverPort`).

---

## `src/<package>/application/`

Orchestration. Coordonne les ports du domaine pour réaliser des cas d'usage concrets.

### `application/use_cases/`

Un fichier = un cas d'usage = une seule responsabilité.

Fournis par le framework : `CreateUseCase`, `ReadUseCase`, `UpdateUseCase`, `DeleteUseCase`, `FindAllUseCase`,
`DuplicateUseCase`, `PurgeUseCase`.

> Ajoute ici tes use cases spécifiques (ex: `FindByNameUseCase`).

### `application/services/`

Façade qui regroupe les use cases d'une entité sous une API cohérente.
Les adapters inbound (FastAPI, MCP...) ne parlent qu'aux services.

`BaseService` est fourni par le framework. Étends-le pour ajouter tes méthodes métier.

```python
class IngredientService(BaseService[Ingredient]):
    async def find_by_name(self, name: str) -> list[Ingredient]:
        ...
```

---

## `src/<package>/adapters/`

Les implémentations concrètes des ports. Ils dépendent du domaine, jamais l'inverse.

### `adapters/inbound/`

Points d'entrée de l'application (ce qui déclenche des actions).

- Routeurs FastAPI
- Outils MCP (FastMCP)
- Commandes CLI
- Workers planifiés
- Adapters agent comme LangGraph ou Pydantic AI

### `adapters/inbound/schemas/`

Les schémas Pydantic de validation des données entrantes/sortantes.
Ils ne doivent pas fuiter dans le domaine.

`BaseSchema` est fourni par le framework comme base commune.

### `adapters/outbound/`

Implémentations des ports de persistance et de logging.

Fournis par le framework :

- `InMemoryRepository` — dev / tests
- `DuckDBRepository` — fichier local (CSV, Parquet…)
- `MongoDBRepository` — production
- `ConsoleLogger` — logging structuré en console

> Étends ces classes pour brancher ton entité sur un repository concret.

---

## `src/<package>/infrastructure/`

Configuration et assemblage. Ne contient pas de logique métier.

- `config.py` / `AppConfig` — lecture du `config.yaml` (quel repository, quelle DB…)
- `container.py` *(dans ton app)* — instancie et injecte les dépendances (DI manuel)
- `api.py` / `mcp.py` *(dans ton app)* — monte les adapters sur le serveur

---

## Résumé

| Dossier           | Rôle                          | Dépend de                 |
|-------------------|-------------------------------|---------------------------|
| `src/<package>/domain/`                  | Logique métier pure           | Rien                                                |
| `src/<package>/application/`             | Orchestration des cas d'usage | `src/<package>/domain/`                             |
| `src/<package>/adapters/`                | Implémentations concrètes     | `src/<package>/domain/`, `src/<package>/application/` |
| `src/<package>/infrastructure/`          | Config & assemblage           | Tout                                                |
