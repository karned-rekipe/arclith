# HTTP Conventions — REST SOTA

## Vue d'ensemble

Ce document définit les conventions HTTP/REST production-ready pour les APIs construites avec `arclith`.
Toutes les fonctionnalités SOTA sont implémentées via des middlewares automatiques + patterns routers.

**Fonctionnalités clés :**

- ✅ Headers Location/Content-Location (RFC 7231)
- ✅ ETag/If-Match optimistic locking (RFC 7232)
- ✅ Cache-Control par verbe/ressource (RFC 7234)
- ✅ Prefer: return=minimal|representation (RFC 7240)
- ✅ Link headers HATEOAS (RFC 8288)
- ✅ Idempotency-Key (draft-ietf-httpapi)
- ✅ 422 Unprocessable Entity vs 400

---

## Status Codes (SOTA)

Tous les endpoints FastAPI DOIVENT déclarer explicitement leur `status_code` et `responses`.

### POST — Create

| Endpoint             | Status                        | Response Body                   | Headers                      | Cas                            |
|----------------------|-------------------------------|---------------------------------|------------------------------|--------------------------------|
| `POST /v1/resources` | **201 Created**               | `{ "data": { "uuid": "..." } }` | `Location`, `Link`           | Succès création                |
|                      | **2xx original rejoué**       | `{ "data": { "uuid": "..." } }` | `X-Idempotency-Replay: true` | Cache hit idempotency          |
|                      | **400 Bad Request**           | `{ "detail": "..." }`           | —                            | Erreur syntaxe (JSON malformé) |
|                      | **422 Unprocessable Entity**  | `{ "detail": [...] }`           | —                            | Validation métier échouée      |
|                      | **500 Internal Server Error** | `{ "detail": "..." }`           | —                            | Erreur serveur                 |

**Convention SOTA :**

1. **Body minimal** : retourner `{ "data": { "uuid": "..." } }` uniquement (pas l'objet complet)
2. **Location header** : `Location: /v1/resources/{uuid}` (RFC 7231)
3. **Link header** : `Link: </v1/resources/{uuid}>; rel="self", ...` (RFC 8288 - HATEOAS)
4. **Prefer header** : Si client envoie `Prefer: return=representation` → retourner objet complet (RFC 7240)
5. **Idempotency-Key** : Header optionnel (requis en prod e-commerce) → rejoue la réponse `2xx` cachée (voir `docs/idempotency.md`)

**Exemple cURL :**

```bash
# Minimal (défaut)
curl -X POST /v1/ingredients \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name": "Farine"}'

# Response:
# HTTP/1.1 201 Created
# Location: /v1/ingredients/01951234-5678-7abc
# Link: </v1/ingredients/01951234-5678-7abc>; rel="self", </v1/ingredients>; rel="collection"
# { "status": "success", "data": { "uuid": "01951234-5678-7abc" } }

# Full representation
curl -X POST /v1/ingredients \
  -H "Prefer: return=representation" \
  -d '{"name": "Farine"}'

# Response:
# HTTP/1.1 201 Created
# Location: /v1/ingredients/01951234-5678-7abc
# { "status": "success", "data": { "uuid": "...", "name": "Farine", "version": 1, ... } }
```

### GET — Read Single Resource

| Endpoint                   | Status               | Response Body                        | Headers                         | Cas                                   |
|----------------------------|----------------------|--------------------------------------|---------------------------------|---------------------------------------|
| `GET /v1/resources/{uuid}` | **200 OK**           | `{ "data": { "uuid": "...", ... } }` | `ETag`, `Cache-Control`, `Link` | Ressource trouvée                     |
|                            | **304 Not Modified** | ∅                                    | `ETag`                          | If-None-Match match (cache valide)    |
|                            | **404 Not Found**    | `{ "detail": "..." }`                | —                               | Ressource inexistante ou soft-deleted |

**Convention SOTA :**

1. **ETag header** : `ETag: "v{version}"` (ex: `"v1"`, `"v42"`) → RFC 7232
2. **Cache-Control** : `Cache-Control: private, max-age=300` (5 min) → RFC 7234
3. **Link header** : `Link: </v1/resources/{uuid}>; rel="self", </v1/resources/{uuid}/duplicate>; rel="duplicate"`
4. **If-None-Match** : Client peut envoyer `If-None-Match: "v1"` → 304 si inchangé

**Exemple cURL :**

```bash
# Première requête
curl -i /v1/ingredients/01951234-5678-7abc

# Response:
# HTTP/1.1 200 OK
# ETag: "v1"
# Cache-Control: private, max-age=300
# Link: </v1/ingredients/01951234-5678-7abc>; rel="self", </v1/ingredients>; rel="collection"
# { "data": { "uuid": "...", "name": "Farine", "version": 1 } }

# Revalidation (après expiration cache)
curl -H 'If-None-Match: "v1"' /v1/ingredients/01951234-5678-7abc

# Response si inchangé:
# HTTP/1.1 304 Not Modified
# ETag: "v1"
# (pas de body)
```

### GET — List / Collection

| Endpoint            | Status              | Response Body                            | Headers                          | Cas                        |
|---------------------|---------------------|------------------------------------------|----------------------------------|----------------------------|
| `GET /v1/resources` | **200 OK**          | `{ "data": [...], "pagination": {...} }` | `X-Total-Count`, `Cache-Control` | Liste (vide ou non)        |
|                     | **400 Bad Request** | `{ "detail": "..." }`                    | —                                | Paramètres query invalides |

**Convention SOTA :**

1. **Always 200** : Liste vide = `{ "data": [] }`, jamais 404
2. **X-Total-Count** : Header avec count total (utile pour pagination UI)
3. **Cache-Control** : `Cache-Control: private, max-age=60` (1 min, shorter TTL que single)

**Exemple cURL :**

```bash
curl -i '/v1/ingredients?page=1&per_page=20'

# Response:
# HTTP/1.1 200 OK
# X-Total-Count: 42
# Cache-Control: private, max-age=60
# { "data": [...], "pagination": { "total": 42, "page": 1, "pages": 3 } }
```

### PUT — Replace

| Endpoint                   | Status                       | Response Body         | Headers                    | Cas                       |
|----------------------------|------------------------------|-----------------------|----------------------------|---------------------------|
| `PUT /v1/resources/{uuid}` | **204 No Content**           | ∅                     | `Content-Location`, `ETag` | Succès remplacement       |
|                            | **404 Not Found**            | `{ "detail": "..." }` | —                          | Ressource inexistante     |
|                            | **412 Precondition Failed**  | `{ "detail": "..." }` | —                          | If-Match version mismatch |
|                            | **422 Unprocessable Entity** | `{ "detail": [...] }` | —                          | Validation métier échouée |

**Convention SOTA :**

1. **If-Match requis** : Header `If-Match: "v1"` pour optimistic locking (RFC 7232)
2. **412 si mismatch** : Version conflict → client doit re-fetch
3. **Content-Location** : `Content-Location: /v1/resources/{uuid}` (RFC 7231)
4. **New ETag** : `ETag: "v2"` après update réussi

**Exemple cURL :**

```bash
# GET current version
curl -i /v1/ingredients/01951234-5678-7abc
# Returns: ETag: "v1"

# PUT with version check
curl -X PUT /v1/ingredients/01951234-5678-7abc \
  -H 'If-Match: "v1"' \
  -d '{"name": "Nouvelle farine"}'

# Response si succès:
# HTTP/1.1 204 No Content
# Content-Location: /v1/ingredients/01951234-5678-7abc
# ETag: "v2"

# Response si conflict:
# HTTP/1.1 412 Precondition Failed
# { "detail": "Version mismatch: expected v1, current v2" }
```

### PATCH — Partial Update

Identique à PUT (204, If-Match, Content-Location, ETag).

### DELETE — Soft Delete

| Endpoint                      | Status             | Response Body         | Headers                   | Cas                   |
|-------------------------------|--------------------|-----------------------|---------------------------|-----------------------|
| `DELETE /v1/resources/{uuid}` | **204 No Content** | ∅                     | `Cache-Control: no-cache` | Succès soft-delete    |
|                               | **404 Not Found**  | `{ "detail": "..." }` | —                         | Ressource inexistante |

**Convention SOTA :**

1. **Idempotent** : DELETE sur ressource déjà deleted = 204 (pas 404)
2. **Cache-Control** : `no-cache, no-store` (jamais cacher mutations)

### POST — Duplicate

Identique à POST Create (201, Location, Link, UUID seul, Prefer header support).

---

## Headers HTTP (SOTA)

### Request Headers

| Header              | Verbe          | Requis                      | Exemple                                | Rôle                                                   |
|---------------------|----------------|-----------------------------|----------------------------------------|--------------------------------------------------------|
| **Idempotency-Key** | POST           | Recommandé (requis en prod) | `550e8400-e29b-41d4-a716-446655440000` | Prévenir duplicatas (voir `docs/idempotency.md`)       |
| **If-Match**        | PUT/PATCH      | Recommandé                  | `"v1"`                                 | Optimistic locking (version check)                     |
| **If-None-Match**   | GET            | Optionnel                   | `"v1"`                                 | Cache validation (304 si match)                        |
| **Prefer**          | POST/PUT/PATCH | Optionnel                   | `return=representation`                | Demander full object au lieu de minimal                |
| **X-Request-ID**    | ALL            | Optionnel                   | `<uuid>`                               | Tracing distribué (propagé dans `metadata.request_id`) |

### Response Headers

| Header                   | Verbe         | Toujours présent | Exemple                                | Rôle                                                |
|--------------------------|---------------|------------------|----------------------------------------|-----------------------------------------------------|
| **Location**             | POST          | Oui (201)        | `/v1/ingredients/01951234...`          | URL de la ressource créée (RFC 7231)                |
| **Content-Location**     | PUT/PATCH     | Oui (204)        | `/v1/ingredients/01951234...`          | URL de la ressource modifiée (RFC 7231)             |
| **ETag**                 | GET/PUT/PATCH | Oui              | `"v1"`                                 | Version entité pour optimistic locking (RFC 7232)   |
| **Cache-Control**        | ALL           | Oui (middleware) | `private, max-age=300`                 | Directives cache (RFC 7234, voir `docs/caching.md`) |
| **Link**                 | GET/POST      | Oui              | `</v1/ingredients/{uuid}>; rel="self"` | HATEOAS navigation (RFC 8288)                       |
| **X-Total-Count**        | GET (list)    | Oui              | `42`                                   | Total items (pagination)                            |
| **X-Process-Time-Ms**    | ALL           | Oui (middleware) | `18`                                   | Durée traitement API                                |
| **X-Idempotency-Replay** | POST          | Si cache hit     | `true`                                 | Indique réponse rejouée depuis cache                |

---

## 400 vs 422 vs 409

| Status                       | Cas                         | Exemple                                       |
|------------------------------|-----------------------------|-----------------------------------------------|
| **400 Bad Request**          | Erreur syntaxe/format       | JSON malformé, header manquant                |
| **422 Unprocessable Entity** | Validation métier échouée   | `name` vide, email invalide, contrainte check |
| **409 Conflict**             | Contrainte unicité violée   | Doublon `email` unique                        |
| **412 Precondition Failed**  | Version mismatch (If-Match) | Optimistic lock failure                       |

**FastAPI par défaut :**

- Validation Pydantic → **422**
- Exceptions levées → configurable

**Convention _sample :**

```python
responses={
    400: {"description": "Invalid payload"},
    422: {"description": "Validation failed"},
    409: {"description": "Duplicate resource"},
    412: {"description": "Precondition Failed (version mismatch)"},
}
```

---

## Déclaration dans FastAPI

### ✅ SOTA — Déclaration complète

```python
self.router.add_api_route(
    methods=["POST"],
    path="/",
    endpoint = self.create_ingredient,
    summary = "Create ingredient",
    response_model = ApiResponse[IngredientCreatedSchema],  # UUID seul
    status_code = 201,
    responses={
        400: {"description": "Invalid payload"},
        422: {"description": "Validation failed"},
    },
)
```

**Handler signature :**

```python
async def create_ingredient(
        self,
        payload: IngredientCreateSchema,
        response: Response,  # Pour injecter headers
        request: Request,  # Pour construire Location
        prefer: Annotated[str | None, Header()] = None,  # Prefer header
) -> ApiResponse[IngredientCreatedSchema] | ApiResponse[IngredientSchema]:
    result = await self._service.create(...)

    # Location header (RFC 7231)
    response.headers["Location"] = f"/v1/ingredients/{result.uuid}"

    # Link header (RFC 8288)
    response.headers["Link"] = f'<{location}>; rel="self", ...'

    # Prefer header support (RFC 7240)
    if prefer and "return=representation" in prefer.lower():
        return success_response(IngredientSchema.model_validate(result))

    # Default: minimal
    return success_response(IngredientCreatedSchema(uuid = result.uuid))
```

### ❌ Mauvais — Ancien pattern

```python
self.router.add_api_route(
    methods=["POST"],
    path="/",
    endpoint = self.create_ingredient,
    response_model = ApiResponse[IngredientSchema],  # ❌ Objet complet
    status_code = 201,
    # ❌ Pas de responses déclarées
)


async def create_ingredient(self, payload: ...):
    result = await self._service.create(...)
    # ❌ Pas de Location header
    # ❌ Retourne objet complet au lieu de UUID seul
    return success_response(IngredientSchema.model_validate(result))
```

---

## MCP Tools — Retours

Les MCP tools ne retournent **pas** de status codes HTTP — ils retournent des objets JSON ou `None`.

### Convention MCP

| Opération | Retour | Erreur |
|---|---|---|
| Create | `dict` (objet complet) | Exception levée |
| Read | `dict \| None` | `None` si non trouvé (pas d'exception) |
| Update | `dict` (objet mis à jour) ou `None` | Exception si non trouvé |
| Delete | `None` ou `{ deleted: true }` | Exception si non trouvé |
| List | `list[dict]` | Toujours `[]` si vide, jamais `None` |

**Règle :** les MCP tools **ne lèvent pas** HTTPException. Ils retournent `None` ou une liste vide. Les erreurs métier génèrent des exceptions Python classiques (ValueError, RuntimeError).

---

## Résumé SOTA

| Verbe  | Action    | Status | Body                     | Headers                                         |
|--------|-----------|--------|--------------------------|-------------------------------------------------|
| POST   | Create    | 201    | `{ "uuid": "..." }`      | Location, Link, [ETag si Prefer], Cache-Control |
| POST   | Duplicate | 201    | `{ "uuid": "..." }`      | Location, Link                                  |
| GET    | Read One  | 200    | `{ "uuid": "...", ... }` | ETag, Cache-Control, Link                       |
| GET    | List      | 200    | `[...]`                  | X-Total-Count, Cache-Control                    |
| PUT    | Replace   | 204    | ∅                        | Content-Location, ETag, Cache-Control           |
| PATCH  | Partial   | 204    | ∅                        | Content-Location, ETag, Cache-Control           |
| DELETE | Soft      | 204    | ∅                        | Cache-Control                                   |
| DELETE | Purge     | 200    | `{ "purged": N }`        | —                                               |

---

## Principes SOTA

1. **UUID seul en POST** : retourner `{ "data": { "uuid": "..." } }` — client fait GET si besoin
2. **Location header obligatoire** : 201 Created → `Location: /v1/resources/{uuid}`
3. **ETag pour optimistic locking** : remplace `version` dans payload PUT/PATCH
4. **Cache-Control automatique** : middleware injecte selon verbe/ressource
5. **Link headers HATEOAS** : navigation API découvrable (RFC 8288)
6. **Prefer header flexible** : client choisit minimal vs full representation
7. **422 vs 400** : 422 pour validation métier, 400 pour syntaxe
8. **Idempotency-Key e-commerce** : requis en prod pour POST (paiements)

---

## Middleware Stack (ordre)

```
TimingMiddleware          # Mesure temps total (X-Process-Time-Ms)
  └─ CacheControlMiddleware  # Injecte Cache-Control
      └─ ETaggerMiddleware      # Gère ETag/If-Match/If-None-Match
          └─ IdempotencyMiddleware  # Cache POST par Idempotency-Key
              └─ Application Router   # Votre logique métier
```

---

## Références

- **RFC 7231:** [HTTP Semantics](https://www.rfc-editor.org/rfc/rfc7231.html) (Location, Content-Location)
- **RFC 7232:** [Conditional Requests](https://www.rfc-editor.org/rfc/rfc7232.html) (ETag, If-Match, If-None-Match)
- **RFC 7234:** [Caching](https://www.rfc-editor.org/rfc/rfc7234.html) (Cache-Control)
- **RFC 7240:** [Prefer Header](https://www.rfc-editor.org/rfc/rfc7240.html) (return=representation)
- **RFC 8288:** [Web Linking](https://www.rfc-editor.org/rfc/rfc8288.html) (Link header, HATEOAS)
- **RFC 9110:** [HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html) (Latest consolidated)
- **Draft:** [Idempotency-Key](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header)

**Guides complémentaires :**

- `docs/idempotency.md` — E-commerce production patterns
- `docs/caching.md` — Stratégie cache HTTP multi-niveaux
