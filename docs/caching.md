# HTTP Caching Strategy

## Vue d'ensemble

Stratégie de cache HTTP multi-niveaux pour optimiser la bande passante, réduire la latence et améliorer l'expérience
utilisateur.

## Architecture

```
Client (Browser/App)
    ↓ Cache-Control, ETag, If-None-Match
CDN / Reverse Proxy (nginx, CloudFlare)
    ↓ Cache-Control (public/private)
API Gateway / Load Balancer
    ↓
FastAPI + CacheControlMiddleware
    ↓
Application Service
    ↓
Database / Repository
```

## Middleware: CacheControlMiddleware

Injecte automatiquement les headers `Cache-Control` selon le verbe HTTP et le type de ressource.

**Configuration (_sample/config/http.yaml):**

```yaml
cache_control:
  get_single_max_age: 300  # 5 minutes - GET /{uuid}
  get_list_max_age: 60     # 1 minute - GET /
```

### Stratégie par verbe

| Verbe            | Ressource          | Directive               | Raison                                                                           |
|------------------|--------------------|-------------------------|----------------------------------------------------------------------------------|
| **GET**          | Single (`/{uuid}`) | `private, max-age=300`  | Cacheable 5min par le client, pas le CDN (données potentiellement user-specific) |
| **GET**          | Collection (`/`)   | `private, max-age=60`   | Shorter TTL (1min) car changements fréquents                                     |
| **POST**         | Create             | `no-cache, no-store`    | Jamais cacher les mutations                                                      |
| **PUT/PATCH**    | Update             | `no-cache, no-store`    | Jamais cacher les mutations                                                      |
| **DELETE**       | Delete             | `no-cache, no-store`    | Jamais cacher les mutations                                                      |
| **HEAD/OPTIONS** | Metadata           | `public, max-age=86400` | Cacheable 24h par tout le monde                                                  |

### Heuristique ressource unique vs collection

Le middleware détecte automatiquement le type de ressource via le path:

- `/v1/ingredients/01951234-5678-7abc` → **Single** (UUID pattern)
- `/v1/ingredients` → **Collection**
- `/v1/ingredients/search` → **Collection** (action/filter)

**Code:**

```python
def _is_single_resource_path(self, path: str) -> bool:
    """UUID-like pattern detection."""
    parts = path.split("/")
    last_part = parts[-1]
    # UUID format: 32+ hex chars
    return len(last_part) >= 32 and all(c in "0123456789abcdefABCDEF-" for c in last_part)
```

## Directives Cache-Control

### `private` vs `public`

**`private`** — Cacheable uniquement par le client (browser/app), pas par les proxies intermédiaires.

- Utilisé quand: données user-specific (commandes, profil utilisateur)
- Example: `Cache-Control: private, max-age=300`

**`public`** — Cacheable par tout le monde (client, CDN, reverse proxy).

- Utilisé quand: données statiques/publiques (produits, assets)
- Example: `Cache-Control: public, max-age=3600`

**Dans _sample:** Toutes les ressources utilisent `private` car potentiellement multi-tenant.

### `max-age` — TTL en secondes

Durée pendant laquelle la réponse est considérée "fraîche" sans revalidation.

**Recommandations par type:**
| Type | TTL | Justification |
|---|---|---|
| Entité mutable (ingredient, recipe) | 300s (5min) | Balance fraîcheur/performance |
| Collection filtrée | 60s (1min) | Changements fréquents |
| Metadata statique (OPTIONS) | 86400s (24h) | Rarement modifié |
| Assets statiques (non géré par FastAPI) | 31536000s (1 an) | Immutable |

### `no-cache` vs `no-store`

**`no-cache`** — Doit revalider avant utilisation (If-None-Match).

- Header: `Cache-Control: no-cache`
- Utilisé quand: données sensibles mais cacheable avec revalidation

**`no-store`** — Jamais stocker en cache (même pas localement).

- Header: `Cache-Control: no-cache, no-store, must-revalidate`
- Utilisé quand: mutations (POST/PUT/PATCH/DELETE)

**Dans _sample:** Mutations utilisent `no-cache, no-store` pour éviter tout cache.

## Intégration avec ETag

Le cache HTTP est plus efficace couplé avec ETag (RFC 7232).

Dans Arclith, `ETaggerMiddleware` s'applique aux réponses `GET` JSON `2xx` qui exposent un champ
`version` ou `data.version`. Les `POST`, `PUT`, `PATCH` et `DELETE` ne reçoivent pas de header de
cache en sortie; `If-Match` sur `PUT`/`PATCH` reste disponible côté requête pour l'optimistic
locking applicatif.

**Workflow:**

1. **Première requête:**
   ```
   GET /v1/ingredients/01234...
   
   200 OK
   Cache-Control: private, max-age=300
   ETag: "v1"
   { "uuid": "...", "name": "Farine", "version": 1 }
   ```

2. **Requête dans les 5min (cache fresh):**
    - Client utilise la réponse cachée localement (aucune requête réseau)

3. **Requête après 5min (cache stale):**
   ```
   GET /v1/ingredients/01234...
   If-None-Match: "v1"
   
   304 Not Modified  (si version inchangée)
   Cache-Control: private, max-age=300
   ETag: "v1"
   (pas de body)
   
   OU
   
   200 OK  (si version modifiée)
   Cache-Control: private, max-age=300
   ETag: "v2"
   { "uuid": "...", "name": "Farine complète", "version": 2 }
   ```

**Bénéfices:**

- **Bande passante:** 304 évite le transfert du body
- **Latence:** Réponse plus rapide (header-only)
- **Concurrency:** If-Match empêche les lost updates

## Configuration par environnement

### Développement (config/http.yaml)

```yaml
cache_control:
  get_single_max_age: 60   # Court TTL pour voir les changements rapidement
  get_list_max_age: 10
```

### Staging

```yaml
cache_control:
  get_single_max_age: 300  # Simule la prod
  get_list_max_age: 60
```

### Production

```yaml
cache_control:
  get_single_max_age: 600  # 10 minutes (si tolérable)
  get_list_max_age: 120    # 2 minutes
```

**Note:** Pour les données temps-réel (stocks, prix), utiliser `get_list_max_age: 0` (no-store).

## CDN / Reverse Proxy (nginx)

Si l'API est derrière un CDN, les directives `private` empêchent le cache partagé.

**Pour activer le cache CDN (données publiques uniquement):**

1. **Modifier la stratégie middleware:**
   ```python
   # cache_control.py
   if method == "GET" and is_public_resource(path):
       return f"public, max-age={self._get_single_max_age}"
   ```

2. **Configuration nginx:**
   ```nginx
   proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=1g;
   
   location /v1/ {
       proxy_cache api_cache;
       proxy_cache_key "$request_uri";
       proxy_cache_valid 200 5m;
       proxy_cache_use_stale error timeout updating http_500 http_502 http_503;
       
       # Respecter Cache-Control de l'API
       proxy_cache_bypass $http_cache_control;
       
       proxy_pass http://backend;
   }
   ```

## Monitoring

**Headers à surveiller:**

- `X-Cache` (nginx/CDN) — HIT/MISS/BYPASS
- `Age` (nginx/CDN) — Âge du cache en secondes
- `X-Process-Time-Ms` (arclith) — Temps de traitement API

**Métriques:**

- `cache_hit_rate` (CDN) — % de requêtes servies depuis le cache
- `backend_requests_per_second` (API) — Doit diminuer si cache efficace
- `304_responses_per_second` (API) — ETag revalidations

## Cas d'usage E-commerce

### 1. Catalogue produits (lecture intensive)

**Problème:** 10k requêtes/s pour afficher les produits.

**Solution:**

```yaml
cache_control:
  get_single_max_age: 3600  # 1 heure (produit change rarement)
```

```
GET /v1/products/01234...
Cache-Control: public, max-age=3600  # Cacheable par le CDN
ETag: "v1"
```

**Résultat:** 95% cache hit ratio CDN → API ne reçoit que 500 req/s.

### 2. Stock temps-réel (écriture intensive)

**Problème:** Stock change à chaque vente → cache stale = bad UX.

**Solution:**

```yaml
cache_control:
  get_single_max_age: 0  # no-store
```

```
GET /v1/products/01234.../stock
Cache-Control: no-store
```

**Résultat:** Toujours fresh, mais charge serveur élevée → utiliser WebSocket/SSE pour push.

### 3. Panier utilisateur (user-specific)

**Problème:** Données sensibles, ne jamais cacher par le CDN.

**Solution:**

```
GET /v1/cart
Cache-Control: private, max-age=60  # Browser cache OK, CDN non
```

**Résultat:** Client peut rafraîchir localement, mais chaque user hit l'API.

## Désactivation sélective

**Désactiver pour un endpoint spécifique:**

```python
@router.get("/v1/real-time-data")
async def get_real_time_data(response: Response):
    # Override middleware
    response.headers["Cache-Control"] = "no-store"
    ...
```

**Désactiver globalement:**

```yaml
cache_control:
  get_single_max_age: 0
  get_list_max_age: 0
```

## Références

- **RFC 7234:** [Caching](https://www.rfc-editor.org/rfc/rfc7234.html)
- **MDN:** [Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control)
- **Google Web Fundamentals:** [HTTP Caching](https://web.dev/http-cache/)
