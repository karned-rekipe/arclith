# Multi-tenancy — arclith

Un seul déploiement, N clients. Chaque client (tenant) possède ses propres ressources de stockage.
Les utilisateurs d'un même tenant partagent ces ressources.

---

## Deux niveaux d'isolation

Le point clé est de distinguer **à qui appartient la ressource** :

| Niveau | Propriétaire | Exemple | Mode |
|--------|-------------|---------|------|
| **App-level** | Le service lui-même | Bucket S3 d'images de l'appli | `multitenant: false` — credentials statiques dans `config.yaml` |
| **Tenant-level** | Le client | MongoDB du client, bucket S3 du client | `multitenant: true` — credentials résolus depuis Vault par requête |

Les ressources app-level sont **partagées** par tous les utilisateurs, quelle que soit leur organisation.
Les ressources tenant-level sont **isolées** : chaque client a les siennes, ses utilisateurs les partagent entre eux.

---

## Exemple concret

```
Appli
├── Bucket S3 "images"        → app-level, partagé         → config.yaml statique
│
├── Client A
│   ├── MongoDB "client_a"    → tenant-level, isolé         → Vault: rekipe/tenants/client-a
│   └── Bucket S3 "client_a"  → tenant-level, isolé         → Vault: rekipe/tenants/client-a
│
└── Client B
    ├── MongoDB "client_b"    → tenant-level, isolé         → Vault: rekipe/tenants/client-b
    └── Bucket S3 "client_b"  → tenant-level, isolé         → Vault: rekipe/tenants/client-b
```

Le bucket S3 "images" de l'appli n'est **jamais** dans `TenantContext` — il utilise ses credentials statiques.
Les ressources tenant-level sont injectées dans `TenantContext` à chaque requête.

---

## Flux par requête (mode multitenant)

```
Bearer JWT
  → JWKS Keycloak (cache)         — validation de signature
  → claims JWT
  → RoleLicenseValidator           — vérification du role licence (realm_access.roles)
  → tenant_id  (claim "sub")
  → VaultTenantResolver ×N (cache) — résolution parallèle, un resolver par adaptateur tenant-level
  → TenantContext                  — merge de tous les adapters, injecté via ContextVar
  → MongoDB repo      → coords.get("uri"), coords.get("db_name")
  → S3 client tenant  → coords.get("bucket_name"), coords.get("endpoint_url")
```

En mode **single-tenant** (`multitenant: false` sur tous les adapters), le pipeline JWT/Vault est intégralement bypassé.

---

## Configuration

Depuis un projet généré, la configuration minimale MongoDB multitenant + tenant Vault peut être
posée par la CLI :

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mongodb \
  --param db_name=fallback_db \
  --param collection_name=null \
  --param multitenant=true \
  --yes

arclith-cli add-adapter \
  --capability tenant \
  --adapter vault \
  --param addr=http://vault:8200 \
  --param mount=kv \
  --param path_prefix=rekipe/tenants \
  --param tenant_claim=tenant_id \
  --param tenant_uri_ttl=300 \
  --yes
```

```yaml
adapters:
  repository: mongodb
  mongodb:
    multitenant: true      # tenant-level → pipeline JWT/Vault actif
    db_name: fallback_db   # fallback si le secret Vault n'a pas de db_name

# Pas de section "s3_app" ici — c'est une config applicative hors arclith.
# Le bucket app-level est câblé directement dans le container du service.

keycloak:
  url: http://keycloak:8080
  realm: rekipe
  audience: rekipe-api     # optionnel

tenant:
  vault_addr: http://vault:8200
  vault_mount: kv
  vault_path_prefix: rekipe/tenants
  tenant_claim: sub

license:
  role: rekipe:licensed

cache:
  backend: redis            # memory | redis
  redis_url: redis://redis:6379
  jwks_ttl: 3600
  tenant_uri_ttl: 300
```

---

## Câblage dans le container

```python
from arclith.adapters.inbound.fastapi.dependencies import make_inject_tenant_uri
from arclith.adapters.inbound.jwt.decoder import JWTDecoder
from arclith.adapters.inbound.license.validator import RoleLicenseValidator
from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter
from arclith.adapters.outbound.vault.tenant_adapter import VaultTenantResolver

cache = MemoryCacheAdapter()  # ou RedisCacheAdapter(url)

# Ressource app-level : bucket S3 partagé — câblé séparément, hors TenantContext
app_s3_client = S3Client(bucket=config.s3_app.bucket, region=config.s3_app.region)

# Ressources tenant-level : un VaultTenantResolver par adaptateur multitenant
inject_tenant = make_inject_tenant_uri(
    config,
    jwt_decoder=JWTDecoder(
        jwks_uri=f"{config.keycloak.url}/realms/{config.keycloak.realm}/protocol/openid-connect/certs",
        audience=config.keycloak.audience,
        cache=cache,
        ttl_s=config.cache.jwks_ttl,
    ),
    license_validator=RoleLicenseValidator(role=config.license.role),
    tenant_resolvers=[
        VaultTenantResolver("mongodb", addr=..., mount=..., path_prefix=..., cache=cache),
        VaultTenantResolver("s3_client", addr=..., mount=..., path_prefix=..., cache=cache),
    ],
)
```

---

## Secrets Vault par tenant

Un seul secret par tenant, **tous les champs sont passés tels quels** dans `AdapterTenantCoords.params`.
Pas de filtrage, pas d'hypothèse sur les clés — chaque adaptateur lit ce dont il a besoin.

```bash
vault kv put kv/rekipe/tenants/client-a \
  uri="mongodb://user:pass@mongo-a:27017" \
  db_name="client_a" \
  bucket_name="client-a-data" \
  s3_region="eu-west-1" \
  s3_endpoint="https://s3.eu-west-1.amazonaws.com"
```

Le préfixe `rekipe/tenants` vient de `tenant.vault_path_prefix`; `client-a` vient du claim JWT
configuré par `tenant.tenant_claim`. `VaultTenantResolver` lit `kv/<path_prefix>/<tenant_id>` en KV
v2, expose tous les champs tels quels, puis chaque adapter consomme sa propre tranche de
`TenantContext`.

> Les clés peuvent être organisées librement. La convention de nommage (`uri`, `db_name`,
> `bucket_name`...) est définie par le projet et par l'adapter consommateur; arclith ne l'impose pas.

Chaque adaptateur lit sa tranche :

```python
# Dans le repository MongoDB du tenant
coords = get_adapter_tenant_context("mongodb")
uri = coords.get("uri") or self._config.uri
db  = coords.get("db_name") or self._config.db_name

# Dans le client S3 du tenant
coords = get_adapter_tenant_context("s3_client")
bucket   = coords.require("bucket_name")
region   = coords.get("s3_region", "eu-west-1")
endpoint = coords.get("s3_endpoint")

# Dans le client S3 app-level (bucket partagé) — pas de TenantContext
# → credentials statiques depuis config.yaml
```

---

## Stratégie de cache

| Donnée | Clé cache | TTL défaut | Config |
|--------|-----------|------------|--------|
| JWKS Keycloak | `jwks:{jwks_uri}` | 3600 s | `cache.jwks_ttl` |
| Coords tenant (par adaptateur) | `tenant:{adapter}:{tenant_id}` | 300 s | `cache.tenant_uri_ttl` |

### Backends

**`memory`** — zéro dépendance, par worker. Idéal en dev et déploiement mono-worker.

**`redis`** (`arclith[cache]`) — partagé entre tous les workers. Recommandé en production.

### Compromis TTL

- **JWKS** : ≥ 1h recommandé. Vider `jwks:{uri}` après une rotation de clé Keycloak.
- **Coords tenant** : 5 min recommandé. Vider `tenant:{adapter}:{tenant_id}` après une migration de bucket/DB.

---

## Stratégie de licence

Les licences sont des **Keycloak realm roles** portés dans le JWT — zéro appel réseau supplémentaire.

```json
{ "realm_access": { "roles": ["rekipe:licensed"] } }
```

`RoleLicenseValidator` vérifie la présence du rôle configuré. Si absent → HTTP 403.

### Granularité possible

| Role | Usage |
|------|-------|
| `rekipe:licensed` | Accès de base |
| `rekipe:premium` | Fonctionnalités avancées |
| `rekipe:trial` | Accès limité (durée, quota) |

### Gestion via API Keycloak Admin

```bash
# Créer le rôle
curl -X POST "$KC/admin/realms/rekipe/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "rekipe:licensed"}'

# Assigner à un utilisateur
curl -X POST "$KC/admin/realms/rekipe/users/$USER_ID/role-mappings/realm" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '[{"name": "rekipe:licensed"}]'
```

La révocation prend effet à l'expiration du token. Avec des tokens courts (5-15 min, défaut Keycloak), c'est suffisant.
