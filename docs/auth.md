# Authentification & Autorisation — arclith

Pipeline JWT Keycloak mutualisé FastAPI + FastMCP. Un seul cœur (`auth_pipeline.py`), deux wrappers minces.

---

## Architecture

```
config.yaml (keycloak / tenant / license / cache)
    │
    └─► Arclith.auth_dependency(transport)
            │
            ├─► JWTDecoder          ← valide signature RS256 via JWKS Keycloak (cache)
            ├─► RoleLicenseValidator ← vérifie realm_access.roles (optionnel)
            └─► VaultTenantResolver  ← résout les credentials tenant (optionnel, multitenant)
                        │
                        ▼
              run_auth_pipeline(headers, ...)          ← transport-agnostique
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
  fastapi/auth.py           fastmcp/auth.py
  make_require_auth()        make_require_auth_tool()
  → HTTPException(401/403)   → PermissionError("401: ...")
            │
            ▼
  TenantContext injecté dans ContextVar (mode multitenant uniquement)
```

### Composants clés

| Fichier | Rôle |
|---|---|
| `adapters/inbound/auth_pipeline.py` | Cœur du pipeline — unique source de vérité |
| `adapters/inbound/fastapi/auth.py` | Wrapper FastAPI : `make_require_auth()` |
| `adapters/inbound/fastmcp/auth.py` | Wrapper FastMCP : `make_require_auth_tool()` |
| `adapters/inbound/fastapi/dependencies.py` | Pipeline complet multitenant (FastAPI) |
| `adapters/inbound/fastmcp/dependencies.py` | Pipeline complet multitenant (FastMCP) |
| `adapters/inbound/jwt/decoder.py` | `JWTDecoder` — JWKS Keycloak avec cache |
| `adapters/inbound/license/validator.py` | `RoleLicenseValidator` — vérifie un realm role |
| `adapters/outbound/vault/tenant_adapter.py` | `VaultTenantResolver` — résout les coords tenant |
| `adapters/context.py` | `ContextVar` tenant par requête |
| `arclith.py` | `Arclith.auth_dependency(transport)` — factory depuis config |

---

## Configuration

Depuis un projet généré par `arclith-cli`, la configuration Keycloak peut être
ajoutée sans toucher aux routers ni aux tools :

```bash
arclith-cli add-adapter \
  --capability auth \
  --adapter keycloak \
  --param url=http://keycloak:8080 \
  --param realm=rekipe \
  --param audience=rekipe-api \
  --param client_id=swagger-public \
  --yes
```

Le CLI génère `config/adapters/inbound/keycloak.yaml`, chargé comme section
`keycloak` par `Arclith("config")`. `audience` valide les tokens reçus par
l'API ou les tools MCP. `client_id` sert uniquement au client public Swagger UI
OAuth2 PKCE ; il peut différer de l'audience si le realm sépare clients front,
Swagger et services machine-to-machine.

```yaml
# config/adapters/inbound/keycloak.yaml

url: http://keycloak:8080        # URL de base Keycloak
realm: rekipe                    # Realm cible
audience: rekipe-api             # Vérification aud dans le JWT (null = désactivé)
client_id: swagger-public        # Client public Swagger UI OAuth2 PKCE
```

La licence par rôle Keycloak se configure aussi sans changer les routers FastAPI
ni les tools MCP :

```bash
arclith-cli add-adapter \
  --capability license \
  --adapter role \
  --param role=rekipe:licensed \
  --yes
```

Le CLI génère `config/adapters/inbound/license.yaml`, chargé comme section
`license` par `Arclith("config")`.

```yaml
# config/adapters/inbound/license.yaml
role: rekipe:licensed
```

Si `config.license` existe, `Arclith.auth_dependency()` ajoute automatiquement
`RoleLicenseValidator(config.license.role)` au pipeline partagé FastAPI/MCP. Si
la section est absente, seul le JWT est vérifié. Un token absent ou invalide
reste une erreur `401`, tandis qu'un token valide sans le rôle demandé retourne
`403`.

Les autres sections restent dans leurs fichiers de configuration dédiés ou dans
un `config.yaml` consolidé selon le mode de déploiement :

```yaml
# config.yaml consolidé

license:
  role: rekipe:licensed            # Realm role requis — omis = pas de vérification licence

tenant:
  vault_addr: http://vault:8200
  vault_mount: kv
  vault_path_prefix: rekipe/tenants
  tenant_claim: sub                # Claim JWT utilisé comme tenant_id (défaut: sub)

cache:
  backend: memory                  # memory (dev/mono-worker) | redis (prod/multi-worker)
  redis_url: redis://redis:6379
  jwks_ttl: 3600                   # TTL cache JWKS en secondes
  tenant_uri_ttl: 300              # TTL cache coords tenant en secondes
```

> **Multi-worker / Kubernetes :** toujours `cache.backend: redis` en production.
> Chaque worker avec `memory` maintient son propre cache — le JWKS sera re-fetché à chaque restart.

---

## FastAPI — Cas d'usage

### 1. Protéger un router entier

Toutes les routes du router exigent un token valide.

```python
from fastapi import APIRouter, Depends
from arclith import Arclith

arclith = Arclith("config.yaml")
require_auth = arclith.auth_dependency()  # transport="api" par défaut

router = APIRouter(
    prefix="/v1/recipes",
    tags=["recipes"],
    dependencies=[Depends(require_auth)],  # ✅ toutes les routes protégées
)
```

### 2. Protéger une route individuelle

```python
router = APIRouter(prefix="/v1/recipes", tags=["recipes"])

# Route publique
router.add_api_route(methods=["GET"], path="/public", endpoint=self.public_endpoint)

# Route protégée
router.add_api_route(
    methods=["POST"],
    path="/",
    endpoint=self.create_recipe,
    dependencies=[Depends(require_auth)],  # ✅ cette route uniquement
    status_code=201,
)
```

### 3. Injecter les claims dans un endpoint

```python
from typing import Annotated

async def create_recipe(
    payload: RecipeCreateSchema,
    claims: Annotated[dict, Depends(require_auth)],  # ✅ claims injectés
) -> RecipeCreatedSchema:
    created_by = claims.get("sub")
    ...
```

### 4. Vérifier un rôle spécifique dans un endpoint

```python
from fastapi import HTTPException

async def admin_endpoint(
    claims: Annotated[dict, Depends(require_auth)],
) -> ...:
    roles = claims.get("realm_access", {}).get("roles", [])
    if "rekipe:admin" not in roles:
        raise HTTPException(status_code=403, detail="Rôle admin requis")
    ...
```

### 5. Pipeline complet — auth + licence + tenant (multitenant)

Le pipeline multitenant est câblé **une seule fois** dans le container, via un middleware global sur le router.
Il n'est pas nécessaire de le répéter sur chaque route.

```python
# infrastructure/recipe_container.py
from arclith.adapters.inbound.fastapi.dependencies import make_inject_tenant_uri
from arclith.adapters.inbound.jwt.decoder import JWTDecoder
from arclith.adapters.inbound.license.validator import RoleLicenseValidator
from arclith.adapters.outbound.vault.tenant_adapter import VaultTenantResolver

inject_tenant = make_inject_tenant_uri(
    config,
    jwt_decoder=JWTDecoder(
        jwks_uri=f"{config.keycloak.url}/realms/{config.keycloak.realm}/protocol/openid-connect/certs",
        audience=config.keycloak.audience,
        cache=cache,
        ttl_s=config.cache.jwks_ttl,
    ),
    license_validator=RoleLicenseValidator(config.license.role),
    tenant_resolvers=[
        VaultTenantResolver("mongodb", addr=config.tenant.vault_addr, ...),
    ],
)

# adapters/inbound/fastapi/routers/recipe_router.py
router = APIRouter(
    prefix="/v1/recipes",
    dependencies=[Depends(inject_tenant)],  # ✅ auth + licence + tenant par requête
)
```

### 6. Router protégé sans tenant (auth seule)

```python
# Protéger sans résoudre le tenant (service sans multitenant)
require_auth = arclith.auth_dependency()

router = APIRouter(
    prefix="/v1/ingredients",
    dependencies=[Depends(require_auth)],
)
```

---

## FastMCP — Cas d'usage

### 1. Protéger un tool individuellement

```python
from typing import Annotated
import fastmcp
from fastmcp import Context

require_auth_mcp = arclith.auth_dependency(transport="mcp")

@mcp.tool
async def create_recipe(
    name: str,
    ctx: Context,
    _auth: Annotated[dict, Depends(require_auth_mcp)],  # ✅ tool protégé
) -> dict:
    ...
```

### 2. Protéger tous les tools d'une classe

```python
class RecipeMCP:
    def __init__(self, service: RecipeService, logger: Logger, mcp: FastMCP, require_auth) -> None:
        self._service = service
        self._logger = logger
        self._require_auth = require_auth
        self._register_tools(mcp)

    def _register_tools(self, mcp: FastMCP) -> None:
        require_auth = self._require_auth

        @mcp.tool
        async def create_recipe(
            name: str,
            ctx: Context,
            _auth: Annotated[dict, Depends(require_auth)],
        ) -> dict:
            ...

        @mcp.tool
        async def list_recipes(
            ctx: Context,
            _auth: Annotated[dict, Depends(require_auth)],
        ) -> list[dict]:
            ...
```

### 3. Injecter les claims dans un tool

```python
@mcp.tool
async def create_recipe(
    name: str,
    ctx: Context,
    claims: Annotated[dict, Depends(require_auth_mcp)],  # claims nommés
) -> dict:
    created_by = claims.get("sub")
    ...
```

### 4. Pipeline complet multitenant (FastMCP)

```python
from arclith.adapters.inbound.fastmcp.dependencies import make_inject_tenant_uri

inject_tenant_mcp = make_inject_tenant_uri(
    config,
    jwt_decoder=jwt_decoder,
    license_validator=license_validator,
    tenant_resolvers=[VaultTenantResolver("mongodb", ...)],
)

@mcp.tool
async def create_recipe(
    name: str,
    ctx: Context,
    _tenant: Annotated[None, Depends(inject_tenant_mcp)],  # ✅ injecte TenantContext
) -> dict:
    # TenantContext disponible via get_adapter_tenant_context("mongodb")
    ...
```

### 5. Auth seule vs auth + tenant — choisir le bon

| Besoin | FastAPI | FastMCP |
|---|---|---|
| Auth seule | `arclith.auth_dependency()` | `arclith.auth_dependency(transport="mcp")` |
| Auth + licence | `arclith.auth_dependency()` (licence configurée) | Idem |
| Auth + licence + tenant | `make_inject_tenant_uri(config, ...)` | `make_inject_tenant_uri(config, ...)` |

> La licence est automatiquement incluse dans `auth_dependency()` si `config.license` est défini.
> Elle est également incluse dans `make_inject_tenant_uri` si `license_validator` est passé.

---

## `Depends` vs décorateur Python

### Pourquoi `Depends` et non `@decorator`

```python
# ❌ Décorateur Python classique — NE PAS UTILISER
def require_auth_decorator(fn):
    async def wrapper(*args, **kwargs):
        # Pas d'accès au Request FastAPI
        # Swagger UI ne détecte pas le schéma de sécurité
        # Le typage des arguments est perdu
        # Pas d'injection native dans FastMCP
        ...
    return wrapper

@require_auth_decorator
async def my_endpoint():
    ...
```

```python
# ✅ Depends — approche canonique
async def my_endpoint(
    claims: Annotated[dict, Depends(require_auth)],
) -> ...:
    # Swagger UI détecte HTTPBearer → bouton "Authorize" actif
    # claims typé : dict — mypy/pyright satisfaits
    # FastAPI injecte automatiquement depuis le schéma OpenAPI
    # FastMCP idem via son propre système de dépendances
    ...
```

**Avantages de `Depends` :**

1. **Swagger UI** — avec `config.keycloak`, le bouton "Authorize" expose le schéma OAuth2 PKCE Keycloak.
2. **Typage complet** — `Annotated[dict, Depends(...)]` est visible par mypy/pyright.
3. **Composabilité** — plusieurs `Depends` peuvent se chaîner (`inject_tenant` dépend lui-même du JWT).
4. **Testabilité** — `app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}` pour les tests.
5. **Unification FastAPI / FastMCP** — même mécanique de dépendances dans les deux frameworks.

### Surcharge avec `dependency_overrides` (tests)

```python
# Dans les tests FastAPI
app.dependency_overrides[require_auth] = lambda: {"sub": "test-user-id"}

# Dans les tests FastMCP
# Mocker inject_tenant ou require_auth selon le cas
```

---

## Swagger UI — tester avec un Bearer Token

Quand `config.keycloak` est présent, `Arclith.fastapi()` :
1. Injecte le schéma OAuth2 PKCE dans l'OpenAPI spec (`/openapi.json`)
2. Pré-configure `swagger_ui_init_oauth` avec `clientId` et PKCE
3. Remplace le schéma `HTTPBearer` généré par FastAPI par le seul schéma
   `keycloak` pour éviter un champ bearer vide et confus dans Swagger UI

Le bouton **"Authorize"** apparaît dans Swagger UI (`/docs`) avec un seul schéma
`keycloak (OAuth2, authorizationCode)`.

**Option A — OAuth2 PKCE (recommandé en dev et démonstration)** :
1. Cliquer "Authorize"
2. Sélectionner le schéma `keycloak (OAuth2, authorizationCode)`
3. Scopes : `openid profile`
4. Keycloak redirige → login → token automatiquement injecté

**Option B — bearer machine-to-machine hors Swagger UI** :
Swagger UI reste volontairement en OAuth2 PKCE. Les clients techniques, tests
automatisés, MCP HTTP/SSE et appels Postman/curl utilisent le même pipeline
serveur avec `Authorization: Bearer <access_token>`.

```bash
# Obtenir un token Keycloak (client_credentials pour M2M)
curl -s -X POST \
  "http://keycloak:8080/realms/rekipe/protocol/openid-connect/token" \
  -d "grant_type=client_credentials&client_id=my-service&client_secret=$SECRET" \
  | jq -r .access_token

# Appeler une route protégée avec ce token
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/recipes
```

---

## Granularité par rôle — patterns avancés

### Vérification inline dans un endpoint

```python
async def my_endpoint(
    claims: Annotated[dict, Depends(require_auth)],
) -> ...:
    roles: list[str] = claims.get("realm_access", {}).get("roles", [])
    if "rekipe:admin" not in roles:
        raise HTTPException(403, "Rôle admin requis")
```

### Dependency réutilisable par rôle

```python
def require_role(role: str) -> Callable:
    """Factory — retourne un Depends vérifiant un rôle Keycloak spécifique."""
    require_auth = arclith.auth_dependency()

    async def _check(claims: Annotated[dict, Depends(require_auth)]) -> dict:
        roles: list[str] = claims.get("realm_access", {}).get("roles", [])
        if role not in roles:
            raise HTTPException(403, f"Rôle requis : {role}")
        return claims

    return _check

# Usage
require_admin = require_role("rekipe:admin")
require_premium = require_role("rekipe:premium")

router.add_api_route(
    methods=["DELETE"],
    path="/purge",
    endpoint=self.purge,
    dependencies=[Depends(require_admin)],  # admin uniquement
    status_code=200,
)
```

### Rôles disponibles (exemple Rekipe)

| Rôle | Usage |
|---|---|
| `rekipe:licensed` | Accès de base (vérifié automatiquement si `config.license.role` est défini) |
| `rekipe:premium` | Fonctionnalités avancées |
| `rekipe:admin` | Administration (purge, management) |
| `rekipe:trial` | Accès limité (durée, quota) |

---

## Limitations et points de vigilance

### Transport stdio — incompatible avec l'auth

Le transport MCP `stdio` ne supporte pas les headers HTTP. Toute authentification JWT est impossible.
**Ne pas utiliser stdio en production.** Voir ADR-007 dans `docs/decisions.md`.

```
✅ streamable-http   → headers disponibles, auth JWT fonctionnelle
✅ SSE               → headers disponibles, auth JWT fonctionnelle
❌ stdio             → pas de headers, auth impossible
```

### Traitements longs et expiration de token

Les JWT Keycloak ont une durée de vie courte (5–15 minutes par défaut).
Pour les traitements longs passant par un event bus (Kafka, RabbitMQ) :

**⚠️ Ne jamais transmettre le JWT brut dans la payload d'un message.**

Raisons :
- Le token expirera avant ou pendant le traitement
- Le consumer n'a pas de mécanisme de refresh (pas de `refresh_token` en M2M)
- Le token peut être révoqué entre l'émission et la consommation

**Pattern correct — extraire le `tenant_id` avant l'envoi :**

```python
# Dans le service producteur (API FastAPI)
async def schedule_long_task(
    payload: TaskPayload,
    claims: Annotated[dict, Depends(require_auth)],
) -> ...:
    tenant_id = claims["sub"]  # ✅ extraire l'identifiant stable
    # Passer tenant_id dans le message, pas le JWT
    await event_bus.publish("tasks", {"tenant_id": tenant_id, **payload.model_dump()})
```

```python
# Dans le service consommateur (worker)
async def process_task(message: dict) -> None:
    tenant_id = message["tenant_id"]
    # Résoudre les credentials via Vault directement (pas de JWT)
    coords = await vault_resolver.resolve(tenant_id)
    ...
```

### Multi-worker / Kubernetes — cache Redis obligatoire

En mode single-worker (dev), `cache.backend: memory` suffit.
En production (plusieurs replicas), chaque worker a son propre cache mémoire :
- Le JWKS est re-fetché par chaque worker à son démarrage
- Les coords tenant ne sont pas partagées entre workers

```yaml
# Production obligatoire
cache:
  backend: redis
  redis_url: redis://redis:6379
  jwks_ttl: 3600
  tenant_uri_ttl: 300
```

### Single-tenant sans Keycloak

Si `config.keycloak` est absent :
- `Arclith.auth_dependency()` lève `RuntimeError`
- `make_inject_tenant_uri` avec `multitenant: false` est un no-op (aucune vérification)
- Les services internes (appelés uniquement par des couches supérieures déjà authentifiées) peuvent omettre `config.keycloak`

```yaml
# Service interne sans auth directe
adapters:
  repository: mongodb
  mongodb:
    multitenant: false  # mono-tenant, pas de Keycloak requis
# Pas de section keycloak — les appels arrivent déjà authentifiés depuis la couche supérieure
```

---

## Récapitulatif des patterns

| Scénario | FastAPI | FastMCP |
|---|---|---|
| Auth seule, router entier | `APIRouter(dependencies=[Depends(require_auth)])` | Depends sur chaque tool |
| Auth seule, route unique | `add_api_route(..., dependencies=[Depends(require_auth)])` | `_auth: Annotated[dict, Depends(require_auth_mcp)]` |
| Claims dans handler | `claims: Annotated[dict, Depends(require_auth)]` | Idem avec `ctx: Context` en plus |
| Auth + licence | `auth_dependency()` avec `config.license` défini | Idem |
| Auth + licence + tenant | `Depends(make_inject_tenant_uri(...))` sur le router | `Depends(make_inject_tenant_uri(...))` dans le tool |
| Vérif rôle custom | `require_role("rekipe:admin")` inline ou factory | Idem, vérif inline après `Depends` |
| Tests unitaires | `app.dependency_overrides[fn] = lambda: {...}` | Mock `inject_tenant_uri` |
| Service interne sans auth | Omettre `config.keycloak`, `multitenant: false` | Idem |

---

## Références

- `arclith/adapters/inbound/auth_pipeline.py` — cœur du pipeline
- `arclith/adapters/inbound/fastapi/auth.py` — wrapper FastAPI
- `arclith/adapters/inbound/fastmcp/auth.py` — wrapper FastMCP
- `docs/multitenant.md` — détail du pipeline multitenant
- `docs/decisions.md` — ADR-007 (stdio), ADR-008 (pipeline mutualisé)
- `SKILLS.md` → SK-F09 — recette pas-à-pas
