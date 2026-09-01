# Capability Embedding

`embedding` transforme des textes en vecteurs numériques derrière un port
outbound provider-neutral. Le port calcule seulement les vecteurs : il ne
stocke ni document, ni chunk, ni conversation.

## Choisir La Bonne Primitive

| Besoin | Primitive Arclith | Responsabilité |
|---|---|---|
| produire une réponse ou une structure | `llm` | complétion et raisonnement |
| transformer du texte en vecteur | `embedding` | calcul numérique sans persistance |
| rechercher les vecteurs voisins | `vector-store` | indexation et recherche vectorielle |
| conserver l'entité et ses métadonnées | `repository` | source de vérité métier |
| conserver le contenu binaire | `storage` | fichiers et blobs |

Un pipeline RAG assemble donc explicitement les responsabilités :

```text
document source -> chunks -> EmbeddingPort -> vector-store
       |                                      |
       +-> repository/storage (source)        +-> index dérivé
```

L'index vectoriel reste reconstruisible. Le service consommateur doit conserver
avec chaque entrée au moins le modèle, la dimension, le hash du contenu et la
stratégie de chunking afin de pouvoir détecter puis réindexer un contenu obsolète.

## Contrat Commun

```python
from arclith import EmbeddingPort, EmbeddingText


async def embed_titles(embedding: EmbeddingPort) -> list[list[float]]:
    response = await embedding.embed_texts(
        [
            EmbeddingText(id="doc-1", text="Architecture hexagonale"),
            EmbeddingText(id="doc-2", text="Recherche vectorielle"),
        ]
    )
    return [result.vector for result in response.results]
```

`EmbeddingResponse` garantit :

- au moins un résultat ;
- des indices continus `0..n-1`, dans l'ordre des entrées ;
- un seul `model_name` et une seule dimension pour tout le batch ;
- un vecteur non vide dont la longueur égale `dimensions` ;
- des métriques de tokens optionnelles via `EmbeddingUsage`.

Les entrées vides ou composées uniquement d'espaces sont rejetées avant tout
appel provider. Les adapters concrets traduisent leurs erreurs en
`EmbeddingUnavailable`, `EmbeddingAuthenticationError`,
`EmbeddingRateLimitError`, `EmbeddingInvalidInput` ou
`EmbeddingDimensionMismatch`. Les messages ne doivent jamais inclure de secret
ou d'URL contenant des credentials.

## Adapter Deterministic

`deterministic` ne requiert aucune dépendance externe. Pour un même
`model_name`, un même texte et une même dimension, il produit le même vecteur
entre deux processus. Il sert aux tests, aux POC et aux smokes locaux ; il ne
modélise aucune proximité sémantique réelle et ne doit pas être utilisé comme
moteur de recherche en production.

```bash
arclith-cli add-adapter \
  --capability embedding \
  --adapter deterministic \
  --param model_name=deterministic-test \
  --param dimensions=1536 \
  --param batch_size=64 \
  --param normalize=true \
  --yes
```

La commande est idempotente et écrit
`config/adapters/outbound/embedding.yaml` :

```yaml
adapter: deterministic
model_name: deterministic-test
dimensions: 1536
batch_size: 64
normalize: true
multitenant: false
```

Le fichier scoped contient son propre sélecteur `adapter`. Il n'ajoute aucune
clé à `config/adapters/adapters.yaml`.

## Assemblage

```python
from arclith import Arclith, EmbeddingText

app = Arclith("config")
embedding = app.embedding()

response = await embedding.embed_texts(
    [EmbeddingText(id="smoke", text="bonjour")]
)
assert response.dimensions == 1536
assert len(response.results[0].vector) == 1536
```

Une application peut fournir un `EmbeddingRegistry` à `app.embedding()` pour
enregistrer un backend propre au projet sans importer son SDK dans le domaine.

## Dimension Et Normalisation

La dimension configurée doit être identique à celle de la collection du
vector-store. Cette vérification doit avoir lieu à l'assemblage ou avant la
première écriture ; tronquer ou compléter silencieusement un vecteur rendrait
l'index incohérent.

Avec `normalize: true`, l'adapter déterministe applique une normalisation L2.
Les futurs providers peuvent déjà retourner des vecteurs normalisés ou proposer
leur propre option. Le service doit documenter la métrique de distance choisie
avec le vector-store et ne pas supposer que tous les providers ont la même
stratégie.

## Conversations Et Vie Privée

L'historique de chat ne doit pas être vectorisé automatiquement. Une telle
indexation dupliquerait des données potentiellement personnelles, changerait
leur durée de rétention et créerait un nouvel usage de recherche. Elle exige un
use case explicite, une politique de consentement/rétention, un filtrage des
données sensibles et une procédure de suppression cohérente entre source et
index.

## Validation Locale

```bash
uv run pytest tests/units/domain/ports/test_embedding.py \
  tests/units/adapters/outbound/test_deterministic_embedding.py \
  tests/units/infrastructure/test_embedding_factory.py
uv run --project cli pytest cli/tests/test_embedding_capability.py
make docs
```

Le smoke doit vérifier la dimension, l'ordre des résultats et la stabilité du
vecteur. Une recherche sémantique pertinente reste hors scope de l'adapter
`deterministic`.
