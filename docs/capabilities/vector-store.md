# Vector Store

La capability outbound `vector-store` indexe des projections vectorielles et
retrouve leurs voisins derrière `VectorStorePort`. Elle reste indépendante des
SDK fournisseurs et n'est pas la source de vérité métier par défaut.

## Choisir La Bonne Persistance

| Besoin | Capability | Responsabilité |
|---|---|---|
| conserver les entités métier et leur cycle de vie | `repository` | source de vérité CRUD |
| conserver des fichiers ou blobs | `storage` | octets et métadonnées objet |
| retrouver des contenus proches d'un vecteur | `vector-store` | index de recherche reconstruisible |
| calculer un vecteur depuis du texte | `embedding` | inférence, sans persistance |

Qdrant ou un autre moteur vectoriel ne remplace donc pas automatiquement
`Repository[T]`. Le service consommateur peut faire ce choix explicitement,
mais Arclith traite l'index comme une projection reconstruisible.

## Position Hexagonale

```text
adapter inbound -> use case applicatif -> Repository[T]
                                      -> EmbeddingPort
                                      -> VectorStorePort
```

L'adapter inbound ne connaît ni le SDK ni les types d'un backend vectoriel. Le
use case orchestre la persistance canonique puis l'indexation. En production,
si ces écritures doivent résister à une panne entre les deux étapes, le service
consommateur doit prévoir un mécanisme de reprise ou un outbox ; la capability
n'ajoute pas de synchronisation implicite.

## Contrat V1

```python
from arclith import VectorPoint, VectorSearchQuery, VectorStorePort


async def index_and_search(store: VectorStorePort) -> list[str]:
    await store.ensure_collection()
    await store.upsert(
        [
            VectorPoint(
                id="doc-1",
                vector=[1.0, 0.0, 0.0],
                payload={"kind": "guide", "published": True},
            )
        ]
    )
    hits = await store.search(
        VectorSearchQuery(
            vector=[1.0, 0.0, 0.0],
            filters={"kind": "guide"},
            limit=5,
        )
    )
    return [hit.id for hit in hits]
```

Le contrat accepte uniquement des vecteurs denses et des payloads JSON :
`null`, booléens, nombres finis, chaînes, listes et objets. Les IDs sont des
chaînes provider-neutral ; pour une entité Arclith, utiliser
`str(entity.uuid)`.

Les filtres v1 font un exact-match sur les champs de premier niveau du payload.
Les résultats sont triés du meilleur score au moins bon. Pour `euclid`,
l'adapter mémoire convertit la distance en similarité avec `1 / (1 + distance)`
afin qu'un score supérieur reste meilleur pour les trois métriques.

## Adapter Memory

`memory` fournit une recherche exacte, déterministe et sans dépendance externe.
Il cible les tests, les démonstrations et les smoke tests locaux, pas les grands
volumes ni la recherche approximate-nearest-neighbour.

```bash
arclith-cli add-adapter \
  --capability vector-store \
  --adapter memory \
  --param collection_name=documents \
  --param vector_size=3 \
  --param distance=cosine \
  --yes
```

La commande crée de façon idempotente
`config/adapters/outbound/vector_store.yaml` :

```yaml
adapter: memory
collection_name: documents
vector_size: 3
distance: cosine
multitenant: false
```

Puis l'assemblage passe par la factory publique :

```python
from arclith import Arclith

app = Arclith("config")
vector_store = app.vector_store()
await vector_store.ensure_collection()
```

`ensure_collection()` est idempotente. Les autres opérations échouent avec
`VectorStoreCollectionNotFound` si elle n'a pas encore été appelée. Les upserts
valident tout le batch avant de le modifier et lèvent
`VectorStoreDimensionMismatch` si une dimension diffère de `vector_size`.

## Adapter Qdrant

`qdrant` fournit l'adapter de production dense via le client Python async
officiel. La dépendance reste optionnelle :

```bash
uv add 'arclith[qdrant]'
```

La commande CLI installe l'extra et génère le même fichier scoped que
`memory`, sans écrire la clé API :

```bash
arclith-cli add-adapter \
  --capability vector-store \
  --adapter qdrant \
  --param url=http://localhost:6333 \
  --param collection_name=documents \
  --param vector_size=1536 \
  --param distance=cosine \
  --yes
```

`config/adapters/outbound/vector_store.yaml` :

```yaml
adapter: qdrant
url: "http://localhost:6333"
api_key: null
collection_name: "documents"
vector_size: 1536
distance: cosine
prefer_grpc: false
timeout: 5.0
create_collection: true
multitenant: false
```

Le catalogue ajoute de façon idempotente les mappings suivants dans
`config/secrets.yaml` :

```yaml
resolver: env
mappings:
  adapters.vector_store.api_key: QDRANT_API_KEY
```

`QDRANT_API_KEY` reste optionnelle pour une instance locale. Une URL contenant
des credentials est refusée afin que ceux-ci ne puissent pas fuiter par la
configuration. Si l'endpoint doit lui aussi venir d'un resolver, le service
peut ajouter explicitement `adapters.vector_store.url: QDRANT_URL` à ses
mappings et fournir la variable correspondante.

### Smoke Local

Un `compose.yaml` minimal peut lancer Qdrant sans service annexe :

```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.19.0
    ports:
      - "6333:6333"
      - "6334:6334"
```

```bash
docker compose up -d qdrant
curl --fail http://localhost:6333/healthz
```

Le service consommateur calcule l'embedding avant d'appeler le vector store ;
Qdrant n'est jamais invoqué directement depuis le domaine ou l'adapter
inbound :

```python
from arclith import (
    EmbeddingPort,
    EmbeddingText,
    VectorPoint,
    VectorSearchQuery,
    VectorStorePort,
)


async def index_and_find(
    embedding: EmbeddingPort,
    store: VectorStorePort,
) -> list[str]:
    await store.ensure_collection()
    indexed = await embedding.embed_texts(
        [EmbeddingText(id="guide", text="Guide de démarrage")]
    )
    vector = indexed.results[0].vector
    await store.upsert(
        [
            VectorPoint(
                id="8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07",
                vector=vector,
                payload={"kind": "guide"},
            )
        ]
    )
    hits = await store.search(
        VectorSearchQuery(vector=vector, filters={"kind": "guide"})
    )
    return [hit.id for hit in hits]
```

Avant l'upsert ou la recherche, l'adapter vérifie que la dimension correspond
à `vector_size`, puis mappe les erreurs du SDK vers les erreurs communes. La
page [Embedding](embedding.md) détaille la production du vecteur.

Les filtres Qdrant v1 sont des exact-match sur un champ de premier niveau et
acceptent les chaînes, entiers et booléens pris en charge par `MatchValue`.
Les nombres flottants, `null`, listes et objets restent valides dans les
payloads mais ne sont pas acceptés comme valeur de filtre Qdrant v1.

### Multitenant Et Cycle De Vie

Avec `multitenant: true`, le contexte d'adapter `qdrant` peut fournir `url`,
`api_key` et `collection_name`. Chaque champ absent retombe sur la
configuration single-tenant. L'URL effective est revalidée et aucun message
d'erreur ne contient la clé.

En single-tenant, l'adapter réutilise un unique `AsyncQdrantClient` et expose
`await store.close()` pour le fermer lors de l'arrêt du service. Un client
injecté appartient à l'appelant et n'est pas fermé. En multitenant, un client
isolé est créé pour l'opération puis fermé immédiatement, afin de ne pas
conserver les credentials tenant en cache.

## Erreurs Communes

Les adapters exposent les erreurs provider-neutral suivantes :

- `VectorStoreUnavailable` ;
- `VectorStoreCollectionNotFound` ;
- `VectorStoreDimensionMismatch` ;
- `VectorStorePermissionDenied` ;
- `VectorStoreInvalidPayload`.

Les modèles Pydantic refusent en amont les payloads non JSON, les vecteurs vides
ou non finis et les limites non positives. Les adapters externes doivent mapper
leurs erreurs sans exposer de token, de clé API ni d'URL contenant des
credentials.

## Limites V1

La recherche hybride, les sparse vectors, les named vectors multiples,
recommend/discover, le reranking et la synchronisation automatique avec un
repository sont hors scope. Ils devront étendre le contrat commun sans faire
fuiter de types fournisseur dans le domaine.

## Validation Locale

```bash
uv run pytest tests/units/domain/ports/test_vector_store.py
uv run pytest tests/units/adapters/outbound/test_memory_vector_store.py
uv run --extra qdrant pytest tests/units/adapters/outbound/test_qdrant_vector_store.py
uv run pytest tests/units/infrastructure/test_vector_store_config.py
uv run pytest tests/units/infrastructure/test_vector_store_factory.py
uv run --project cli pytest cli/tests/test_vector_store_capability.py
make docs
```
