# SKILLS.md — Arclith (`arclith`)

## SK-F01 — Ajouter un adaptateur de persistance

**Contexte :** implémenter un nouveau backend de stockage (ex. Redis, PostgreSQL).

### Étapes

1. **Créer** `arclith/adapters/output/<backend>/repository.py`
    - Sous-classer `Repository[T]` (ou `InMemoryRepository` pour partir d'une base)
    - Implémenter les 7 méthodes abstraites : `create`, `read`, `update`, `delete`, `find_all`, `find_deleted`,
      `duplicate`

2. **Brancher** dans `arclith/infrastructure/repository_factory.py`
   ```python
   case "<backend>":
       from arclith.adapters.output.<backend>.repository import <Backend>Repository
       return <Backend>Repository(...)
   ```

3. **Config** — ajouter la nouvelle valeur dans le `Literal` de `AdaptersSettings.repository` (
   `infrastructure/config.py`)

4. **Optional-dep** — ajouter le groupe dans `pyproject.toml` :
   ```toml
   [project.optional-dependencies]
   <backend> = ["<package>==x.y.z"]
   ```

5. **Tests** — `tests/units/adapters/output/<backend>/test_repository.py` : coverage ≥ 90 %

### Validation

```bash
make coverage
```

---

## SK-F02 — Étendre `Entity` avec un nouveau champ commun

**Contexte :** ajouter un champ partagé par toutes les entités (ex. `tenant_id`).

### Étapes

1. `arclith/domain/models/entity.py` — ajouter le champ avec valeur par défaut
2. Vérifier que tous les adaptateurs existants (MongoDB, DuckDB, memory) gèrent le champ
3. Mettre à jour les tests unitaires de `Entity`
4. Bump de version mineure dans `pyproject.toml`

### Validation

```bash
make test
make coverage
```

---

## SK-F03 — Ajouter une méthode de requête au port `Repository`

**Contexte :** ajouter une méthode de recherche (ex. `find_by_name`) au contrat de base.

### Étapes

1. `arclith/domain/ports/repository.py` — déclarer la méthode abstraite
2. Implémenter dans **chacun** des adaptateurs : `InMemoryRepository`, `MongoDBRepository`, `DuckDBRepository`
3. Ajouter dans `BaseService` si elle doit être exposée comme use case standard
4. Mettre à jour les tests de chaque adaptateur

> ⚠️ Un ajout au port de base est un **breaking change** : tous les sous-classeurs existants doivent l'implémenter.
> Préférer un port spécialisé dans le repo consommateur si la méthode n'est pas universelle.

### Validation

```bash
make test
make typecheck
```

---

## SK-F04 — Configurer le mode multitenant

**Contexte :** permettre l'isolation par tenant via `ContextVar`.

### Étapes côté framework (déjà implémenté)

- `arclith/adapters/context.py` : `set_tenant_uri(uri)` / `get_tenant_uri()`
- `arclith/adapters/input/fastmcp/dependencies.py` : `make_inject_tenant_uri(config)`

### Étapes côté implémenteur

1. `config.yaml` : `adapters.multitenant: true`
2. Dans l'adapter d'entrée, avant chaque appel :
   ```python
   from arclith.adapters.context import set_tenant_uri
   set_tenant_uri(uri_resolved_from_request)
   ```
3. `MongoDBRepository` appelle `get_tenant_uri()` automatiquement si `multitenant=true`.

### Validation

- Test unitaire avec deux URIs distinctes : vérifier que les collections MongoDB ciblées sont différentes.

---

## SK-F07 — Implémenter le pipeline d'authentification JWT (SK-AUTH-01)

**Contexte :** ajouter les tests unitaires pour le pipeline JWT mutualisé (actuellement exclu de la coverage).

### Fichiers cibles

```
tests/units/adapters/input/test_auth_pipeline.py    # run_auth_pipeline (tous cas)
tests/units/adapters/input/test_fastapi_auth.py     # make_require_auth (FastAPI)
tests/units/adapters/input/test_fastmcp_auth.py     # make_require_auth_tool (FastMCP)
```

### Cas à couvrir dans `test_auth_pipeline.py`

- Token valide → retourne les claims
- Header `Authorization` absent → `AuthPipelineError(401)`
- Header sans préfixe `Bearer` → `AuthPipelineError(401)`
- `JWTDecoder.decode()` lève une exception → `AuthPipelineError(401)`
- Licence invalide (`LicenseValidator.validate()` retourne False) → `AuthPipelineError(403)`
- Tenant claim absent du token → `AuthPipelineError(401)` (mode multitenant)
- Résolution tenant OK → `TenantContext` injecté dans le `ContextVar`

### Pattern de test (mock JWTDecoder)

```python
from unittest.mock import AsyncMock, MagicMock
from arclith.adapters.input.auth_pipeline import AuthPipelineError, run_auth_pipeline

async def test_valid_token_returns_claims():
    decoder = AsyncMock()
    decoder.decode.return_value = {"sub": "user-123", "realm_access": {"roles": []}}
    claims = await run_auth_pipeline(
        {"Authorization": "Bearer valid-token"},
        jwt_decoder=decoder,
    )
    assert claims["sub"] == "user-123"

async def test_missing_auth_header_raises():
    decoder = AsyncMock()
    with pytest.raises(AuthPipelineError) as exc:
        await run_auth_pipeline({}, jwt_decoder=decoder)
    assert exc.value.status_code == 401
```

### Retirer de coverage omit une fois les tests ajoutés

Dans `pyproject.toml`, retirer les lignes concernées de `[tool.coverage.run] omit`.

---

## SK-F08 — Créer un service avec auth Keycloak complète

**Contexte :** reconstruire `recipe/` ou un nouveau service avec JWT + multitenant.
Voir `SKILLS.md` (workspace racine) → SK-09 et SK-10 pour le câblage complet.

---

## SK-F09 — Sécuriser des routes FastAPI et tools FastMCP avec `require_auth`

**Contexte :** ajouter la protection JWT Keycloak sur des routes ou tools spécifiques.

> Référence complète : `docs/auth.md`

### Prérequis

`config.yaml` doit contenir la section `keycloak` :

```yaml
keycloak:
  url: http://keycloak:8080
  realm: rekipe
  audience: rekipe-api  # null = pas de vérification aud
license:
  role: rekipe:licensed  # optionnel — omis = pas de vérification licence
```

### Étapes — FastAPI

1. **Obtenir la dépendance** depuis `Arclith` :
   ```python
   require_auth = arclith.auth_dependency()  # transport="api" par défaut
   ```

2. **Protéger un router entier** :
   ```python
   router = APIRouter(prefix="/v1/recipes", dependencies=[Depends(require_auth)])
   ```

3. **Protéger une route individuelle** :
   ```python
   router.add_api_route(..., dependencies=[Depends(require_auth)])
   ```

4. **Injecter les claims** dans un handler :
   ```python
   async def my_endpoint(claims: Annotated[dict, Depends(require_auth)]) -> ...:
       user_id = claims.get("sub")
   ```

### Étapes — FastMCP

1. **Obtenir la dépendance MCP** :
   ```python
   require_auth_mcp = arclith.auth_dependency(transport="mcp")
   ```

2. **Protéger un tool** :
   ```python
   @mcp.tool
   async def my_tool(
       name: str,
       ctx: fastmcp.Context,
       _auth: Annotated[dict, Depends(require_auth_mcp)],
   ) -> dict:
       ...
   ```

### Étapes — Pipeline multitenant complet

Voir `docs/multitenant.md` + `docs/auth.md` → section "Pipeline complet".

```python
inject_tenant = make_inject_tenant_uri(config, jwt_decoder=..., license_validator=..., tenant_resolvers=[...])
# FastAPI : router = APIRouter(dependencies=[Depends(inject_tenant)])
# FastMCP : _tenant: Annotated[None, Depends(inject_tenant_mcp)]
```

### Validation

```bash
# Override pour les tests
app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}
make test
```

---

**Contexte :** exposer une nouvelle entité via REST avec les status codes SOTA.

### Étapes

1. **Lire** `docs/http-conventions.md` — connaître les status codes standards

2. **Créer** `adapters/input/fastapi/routers/<entity>_router.py` :
   ```python
   class <Entity>Router:
       def __init__(self, service: <Entity>Service, logger: Logger) -> None:
           self._service = service
           self._logger = logger
           self.router = APIRouter(prefix="/v1/<entities>", tags=["<entities>"])
           self._register_routes()

       def _register_routes(self) -> None:
           # POST — Create (201)
           self.router.add_api_route(
               methods=["POST"],
               path="/",
               endpoint=self.create_<entity>,
               summary="Create <entity>",
               response_model=<Entity>CreatedSchema,
               status_code=201,  # ✅ Explicite
               responses={
                   400: {"description": "Invalid payload"},
                   409: {"description": "<Entity> already exists"},
               },
           )
           # GET — Read One (200 / 404)
           self.router.add_api_route(
               methods=["GET"],
               path="/{uuid}",
               endpoint=self.get_<entity>,
               summary="Get <entity>",
               response_model=<Entity>Schema,
               status_code=200,  # ✅ Explicite
               responses={404: {"description": "<Entity> not found"}},
           )
           # GET — List (200)
           self.router.add_api_route(
               methods=["GET"],
               path="/",
               endpoint=self.list_<entities>,
               summary="List <entities>",
               response_model=list[<Entity>Schema],
               status_code=200,  # ✅ Explicite
           )
           # PUT — Replace (204 / 404)
           self.router.add_api_route(
               methods=["PUT"],
               path="/{uuid}",
               endpoint=self.update_<entity>,
               summary="Replace <entity>",
               status_code=204,  # ✅ No Content
               responses={404: {"description": "<Entity> not found"}},
           )
           # PATCH — Partial Update (204 / 404)
           self.router.add_api_route(
               methods=["PATCH"],
               path="/{uuid}",
               endpoint=self.patch_<entity>,
               summary="Partially update <entity>",
               status_code=204,  # ✅ No Content
               responses={404: {"description": "<Entity> not found"}},
           )
           # DELETE — Soft Delete (204)
           self.router.add_api_route(
               methods=["DELETE"],
               path="/{uuid}",
               endpoint=self.delete_<entity>,
               summary="Delete <entity>",
               status_code=204,  # ✅ No Content
           )
           # DELETE — Purge (200)
           self.router.add_api_route(
               methods=["DELETE"],
               path="/purge",
               endpoint=self.purge_<entities>,
               summary="Purge soft-deleted <entities>",
               status_code=200,  # ✅ OK + body { purged: N }
           )
           # POST — Duplicate (201 / 404)
           self.router.add_api_route(
               methods=["POST"],
               path="/{uuid}/duplicate",
               endpoint=self.duplicate_<entity>,
               summary="Duplicate <entity>",
               response_model=<Entity>CreatedSchema,
               status_code=201,  # ✅ Created
               responses={404: {"description": "<Entity> not found"}},
           )
   ```

3. **Export** — ajouter dans `adapters/input/fastapi/routers/__init__.py` :
   ```python
   from adapters.input.fastapi.routers.<entity>_router import <Entity>Router
   
   __all__ = ["<Entity>Router", ...]
   ```

4. **Register** — importer et enregistrer dans `adapters/input/fastapi/router.py` :
   ```python
   from adapters.input.fastapi.routers import <Entity>Router
   
   def register_routers(app: FastAPI, arclith: Arclith) -> None:
       service, logger = build_<entity>_service(arclith)
       app.include_router(<Entity>Router(service, logger).router)
   ```

5. **Handlers** — lever `HTTPException(status_code=404, detail="...")` si `service.read()` retourne `None`

6. **Validation** — tester avec `pytest` + `TestClient` :
   - Vérifier chaque status code (201, 200, 204, 404, 400)
   - Vérifier que PUT/PATCH/DELETE retournent body vide (`None`)
   - Vérifier que GET list retourne 200 + `[]` si vide (pas 404)

### Validation

```bash
make test
```

### Références

- `docs/http-conventions.md` — conventions complètes
- `_sample/adapters/input/fastapi/routers/ingredient_router.py` — exemple de référence

---

## SK-F06 — Organiser routers FastAPI et tools MCP en sous-dossiers

**Contexte :** structurer les adapters d'entrée pour gérer plusieurs entités proprement.

### Structure recommandée

```
adapters/
  input/
    fastapi/
      routers/
        __init__.py              # Export tous les routers
        ingredient_router.py
        recipe_router.py
        ...
      router.py                  # Register routers (point d'entrée)
      dependencies.py
    fastmcp/
      tools/
        __init__.py              # Export tous les tools
        ingredient_tools.py
        recipe_tools.py
        ...
      tools.py                   # Register tools (point d'entrée)
      prompts/
        __init__.py              # Export tous les prompts
        ingredient_prompts.py
        recipe_prompts.py
        ...
      prompts.py                 # Register prompts (point d'entrée)
      resources/
        __init__.py              # Export toutes les resources
        ingredient_resources.py
        recipe_resources.py
        ...
      resources.py               # Register resources (point d'entrée)
      dependencies.py
```

### Étapes de migration

1. **Créer les sous-dossiers** :
   ```bash
   mkdir -p adapters/input/fastapi/routers
   mkdir -p adapters/input/fastmcp/tools
   mkdir -p adapters/input/fastmcp/prompts
   mkdir -p adapters/input/fastmcp/resources
   ```

2. **Déplacer les fichiers** :
   ```bash
   mv adapters/input/fastapi/*_router.py adapters/input/fastapi/routers/
   mv adapters/input/fastmcp/*_tools.py adapters/input/fastmcp/tools/
   # Renommer et déplacer les fichiers prompts et resources
   mv adapters/input/fastmcp/prompts.py adapters/input/fastmcp/prompts/ingredient_prompts.py
   mv adapters/input/fastmcp/resources.py adapters/input/fastmcp/resources/ingredient_resources.py
   ```

3. **Créer les `__init__.py`** :
   ```python
   # adapters/input/fastapi/routers/__init__.py
   from adapters.input.fastapi.routers.ingredient_router import IngredientRouter
   from adapters.input.fastapi.routers.recipe_router import RecipeRouter
   
   __all__ = ["IngredientRouter", "RecipeRouter"]
   ```
   
   ```python
   # adapters/input/fastmcp/tools/__init__.py
   from adapters.input.fastmcp.tools.ingredient_tools import IngredientMCP
   from adapters.input.fastmcp.tools.recipe_tools import RecipeMCP
   
   __all__ = ["IngredientMCP", "RecipeMCP"]
   ```
   
   ```python
   # adapters/input/fastmcp/prompts/__init__.py
   from adapters.input.fastmcp.prompts.ingredient_prompts import IngredientPrompts
   from adapters.input.fastmcp.prompts.recipe_prompts import RecipePrompts
   
   __all__ = ["IngredientPrompts", "RecipePrompts"]
   ```
   
   ```python
   # adapters/input/fastmcp/resources/__init__.py
   from adapters.input.fastmcp.resources.ingredient_resources import IngredientResources
   from adapters.input.fastmcp.resources.recipe_resources import RecipeResources
   
   __all__ = ["IngredientResources", "RecipeResources"]
   ```

4. **Mettre à jour les imports** dans `router.py`, `tools.py`, `main.py`, etc. :
   ```python
   # Avant
   from adapters.input.fastapi.ingredient_router import IngredientRouter
   from adapters.input.fastmcp.ingredient_tools import IngredientMCP
   from adapters.input.fastmcp.prompts import IngredientPrompts
   from adapters.input.fastmcp.resources import IngredientResources
   
   # Après
   from adapters.input.fastapi.routers import IngredientRouter
   from adapters.input.fastmcp.tools import IngredientMCP
   from adapters.input.fastmcp.prompts import IngredientPrompts
   from adapters.input.fastmcp.resources import IngredientResources
   ```

5. **Mettre à jour les tests** qui importent ces modules :
   ```python
   # Avant
   from adapters.input.fastapi.ingredient_router import IngredientRouter
   
   # Après
   from adapters.input.fastapi.routers import IngredientRouter
   ```

6. **Corriger les `patch()` dans les tests MCP** :
   ```python
   # Avant
   patch("adapters.input.fastmcp.ingredient_tools.inject_tenant_uri")
   
   # Après
   patch("adapters.input.fastmcp.tools.ingredient_tools.inject_tenant_uri")
   ```

7. **Créer les fichiers register pour prompts et resources** :
   ```python
   # adapters/input/fastmcp/prompts.py
   import fastmcp
   from arclith import Arclith
   from adapters.input.fastmcp.prompts import IngredientPrompts
   from infrastructure.ingredient_container import build_ingredient_service
   
   def register_prompts(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
       service, logger = build_ingredient_service(arclith)
       IngredientPrompts(service, logger, mcp)
   ```
   
   ```python
   # adapters/input/fastmcp/resources.py
   import fastmcp
   from arclith import Arclith
   from adapters.input.fastmcp.resources import IngredientResources
   from infrastructure.ingredient_container import build_ingredient_service
   
   def register_resources(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
       service, logger = build_ingredient_service(arclith)
       IngredientResources(service, logger, mcp)
   ```

8. **Mettre à jour main.py** :
   ```python
   # Imports
   from adapters.input.fastmcp.tools import register_tools
   from adapters.input.fastmcp.prompts import register_prompts
   from adapters.input.fastmcp.resources import register_resources
   
   # Dans la fonction MCP runner
   mcp = arclith.fastmcp("MyApp")
   register_tools(mcp, arclith)
   register_prompts(mcp, arclith)
   register_resources(mcp, arclith)
   ```

### Validation

```bash
make test
```

### Avantages

- ✅ Scalable : ajouter de nouvelles entités n'encombre pas le dossier parent
- ✅ Cohérent : même structure pour FastAPI et FastMCP (router.py ↔ tools.py/prompts.py/resources.py)
- ✅ Explicite : les `__init__.py` documentent ce qui est public, les register_*() centralisent l'enregistrement
- ✅ Standard : pattern courant dans les projets Python

### Références

- `_sample/adapters/input/` — implémentation de référence

---

## SK-F10 — Corriger un DeprecationWarning tiers

**Contexte :** une dépendance (directe ou transitive) émet un `DeprecationWarning` visible dans les logs ou les tests.

> ⚠️ **Règle absolue : on ne masque jamais un warning sans corriger sa cause racine.**
> Utiliser `filterwarnings = ["ignore::DeprecationWarning:..."]` dans pytest ou `warnings.filterwarnings("ignore")`
> est interdit. Cela cache la dette sans la réduire et peut dissimuler des régressions futures.

### Protocole de diagnostic

1. **Identifier la chaîne d'import** — lire le stacktrace complet du warning (ou lancer `python -W error::DeprecationWarning -c "import <suspect>"` pour forcer l'exception et obtenir la pile entière).
2. **Localiser le fichier source** — le warning vient d'un `__init__.py` ou d'un module dans `.venv/lib/.../site-packages/`. Lire le fichier pour comprendre QUI l'importe.
3. **Identifier l'entrée d'arclith** — remonter jusqu'au code d'`arclith` qui déclenche la chaîne (ex : paramètre de config d'un serveur tiers).
4. **Corriger à la source** — modifier le code d'`arclith` pour éviter le chemin d'import incriminé (ex : passer `ws="websockets-sansio"` à uvicorn).

### Règle : résoudre les versions avant de bumper

Avant de modifier une contrainte de version dans `pyproject.toml` :

1. **Vérifier quelle version exacte** corrige le comportement ciblé :
   ```bash
   # Vérifier le changelog / release notes du package sur PyPI
   uv run --frozen python -c "import <pkg>; print(<pkg>.__version__)"
   # Tester localement avec la version candidate
   uv add <pkg>==<candidate> --dev  # dans une branche temporaire
   make test  # confirmer la disparition du warning
   ```
2. **Documenter la version** dans l'ADR avant de committer le bump.
3. **Ne jamais bumper en aveugle** avec `>=latest` sans avoir validé le comportement.

### Validation

```bash
# Le warning ne doit plus apparaître
uv run --frozen pytest -v -W error::DeprecationWarning
# La suite de tests reste verte
make test
```
