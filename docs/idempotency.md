# Idempotency — E-commerce Production Guide

## Contexte

L'idempotence garantit qu'une même opération peut être exécutée plusieurs fois sans effet de bord supplémentaire.
Critique pour l'e-commerce où les retries réseau peuvent créer des doublons de paiements ou de commandes.

## Implementation

### Middleware

`IdempotencyMiddleware` intercepte les requêtes POST avec un header `Idempotency-Key` et cache la réponse pendant 24h
par défaut.

**Workflow:**

1. Client envoie `POST /orders` avec `Idempotency-Key: <uuid>`
2. Middleware vérifie le cache
    - **Hit** → rejoue la réponse cachée avec `X-Idempotency-Replay: true`
    - **Miss** → exécute la requête, cache la réponse si 2xx
3. Requêtes suivantes avec la même clé retournent la réponse cachée

**Configuration (_sample/config/http.yaml):**

```yaml
idempotency:
  enabled: true
  ttl_seconds: 86400  # 24 hours
  required: false  # true = reject POST sans Idempotency-Key
```

Le cache utilisé par le middleware est le cache technique Arclith. `cache/memory`
est adapté aux tests et au mono-processus; utiliser `cache/redis` dès que plusieurs
workers, replicas Kubernetes ou processus API/MCP doivent partager les clés
idempotentes.

### Usage Client

**cURL:**

```bash
# Première requête
curl -X POST https://api.example.com/v1/orders \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"product_id": "123", "quantity": 1}'

# Returns: 201 Created
# Response: {"status": "success", "data": {"uuid": "..."}}

# Retry (network timeout, client retente)
curl -X POST https://api.example.com/v1/orders \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"product_id": "123", "quantity": 1}'

# Returns: status original rejoué (cached)
# Response: {"status": "success", "data": {"uuid": "..."}} (same UUID)
# Header: X-Idempotency-Replay: true
```

**JavaScript (Fetch API):**

```javascript
import { v4 as uuidv4 } from 'uuid';

async function createOrder(product_id, quantity) {
  const idempotencyKey = uuidv4();
  
  const response = await fetch('/v1/orders', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey
    },
    body: JSON.stringify({ product_id, quantity })
  });
  
  // Check if response was replayed from cache
  const isReplay = response.headers.get('X-Idempotency-Replay') === 'true';
  
  return {
    data: await response.json(),
    wasRetry: isReplay
  };
}
```

**Python (httpx):**

```python
import httpx
from uuid import uuid4


async def create_order(product_id: str, quantity: int):
    idempotency_key = str(uuid4())

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.example.com/v1/orders",
            json = {"product_id": product_id, "quantity": quantity},
            headers = {"Idempotency-Key": idempotency_key}
        )
        response.raise_for_status()

        was_replay = response.headers.get("X-Idempotency-Replay") == "true"
        return response.json(), was_replay
```

## Cas d'usage E-commerce

### 1. Paiements

**Problème:** Double charge si retry réseau pendant la transaction Stripe/PayPal.

**Solution:**

```python
# Client génère une clé idempotente par intention de paiement
idempotency_key = f"payment-{order_id}-{timestamp}"

# Stripe SDK utilise déjà ce pattern
stripe.Charge.create(
    amount = 1000,
    currency = "eur",
    source = token,
    idempotency_key = idempotency_key  # Stripe API convention
)
```

Notre middleware implémente la même convention pour nos propres endpoints.

### 2. Création de commande

**Problème:** Double commande si timeout pendant la création.

**Solution:**

```bash
# Générer une clé côté client (UUID ou hash stable)
IDEMPOTENCY_KEY=$(uuidgen)

curl -X POST /v1/orders \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -d '{"cart_id": "abc123", "payment_method": "card"}'

# Retry automatique safe (même clé)
curl -X POST /v1/orders \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -d '{"cart_id": "abc123", "payment_method": "card"}'
# → Retourne la même commande (pas de doublon)
```

### 3. Webhooks

**Problème:** Stripe/PayPal peuvent renvoyer le même webhook plusieurs fois.

**Solution:**

```python
# Extraire l'ID événement comme clé idempotente
@app.post("/webhooks/stripe")
async def stripe_webhook(event: dict, request: Request):
    # Stripe envoie event.id dans le payload
    idempotency_key = event["id"]
    
    # Notre middleware détecte automatiquement les doublons
    # via le header Idempotency-Key injecté par un middleware amont
    ...
```

## Limitations

1. **TTL fixe:** Après 24h, la clé expire → retry peut créer un doublon
    - **Mitigation:** Utiliser `required: true` + check DB côté service

2. **Cache partagé:** En multi-tenant, isoler par tenant
    - **Solution:** Cache key = `idempotency:{tenant_id}:{path}:{key}`

3. **Réponse différente:** Si le handler retourne une réponse différente avec la même clé
    - **Détection:** Impossible sans hashing de la réponse (non implémenté)
    - **Best practice:** Clé doit être liée à une intention métier stable

## Comparaison avec l'industrie

| Provider    | Header Name               | TTL                | Required                |
|-------------|---------------------------|--------------------|-------------------------|
| **Stripe**  | `Idempotency-Key`         | 24h                | Recommended             |
| **PayPal**  | `PayPal-Request-Id`       | 45 days            | Optional                |
| **AWS**     | `x-amz-sdk-invocation-id` | Variable           | Optional                |
| **Twilio**  | `Idempotency-Key`         | 24h                | Optional                |
| **Arclith** | `Idempotency-Key`         | 24h (configurable) | Optional (configurable) |

## Monitoring

**Métriques recommandées:**

- `idempotency_cache_hit_rate` — % de requêtes rejouées depuis le cache
- `idempotency_key_missing_rate` — % de POST sans clé
- `idempotency_cache_size` — Nombre de clés actives

**Logs:**

```
🔁 Idempotent request (cache hit) key=550e8400-... path=/v1/orders
💾 Cached idempotent response key=550e8400-... status=201 ttl=86400
```

## Migration en production

**Phase 1:** Déployer avec `required: false` (optionnel)

```yaml
idempotency:
  enabled: true
  required: false
```

**Phase 2:** Monitorer adoption client (logs `idempotency_key_missing_rate`)

**Phase 3:** Passer à `required: true` pour les endpoints critiques

```yaml
idempotency:
  enabled: true
  required: true  # Reject POST without key
```

**Phase 4:** Documenter dans l'API reference (OpenAPI)

```yaml
paths:
  /v1/orders:
    post:
      parameters:
        - name: Idempotency-Key
          in: header
          required: true
          schema:
            type: string
            format: uuid
```

## Références

- **RFC Draft:
  ** [draft-ietf-httpapi-idempotency-key-header](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header)
- **Stripe:** [Idempotent Requests](https://stripe.com/docs/api/idempotent_requests)
- **PayPal:** [Idempotency](https://developer.paypal.com/api/rest/reference/idempotency/)
- **AWS:
  ** [Making idempotent API requests](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/Run_Instance_Idempotency.html)
