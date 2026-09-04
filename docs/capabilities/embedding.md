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

## Adapter OpenAI-Compatible

`openai-compatible` appelle `POST /embeddings` sur un endpoint qui expose le
protocole OpenAI Embeddings. Il convient notamment à LM Studio, vLLM, LocalAI
ou à un mode compatible d'Ollama, à condition que le runtime et le modèle
choisis fournissent réellement cet endpoint.

Installer l'extra HTTP et générer la configuration :

```bash
uv add 'arclith[embedding]>=0.24.0'
arclith-cli add-adapter \
  --capability embedding \
  --adapter openai-compatible \
  --param base_url=http://127.0.0.1:1234/v1 \
  --param api_key=local-dev \
  --param model_name=nomic-embed-text \
  --param dimensions=768 \
  --yes
```

Le nom `nomic-embed-text` n'est qu'un exemple. Copier l'identifiant exact
affiché par le runtime local : Arclith ne choisit, ne télécharge et ne charge
aucun modèle à la place de l'utilisateur.

```yaml
adapter: openai-compatible
base_url: http://127.0.0.1:1234/v1
api_key: local-dev
model_name: nom-exact-du-modele-local
dimensions: 768
batch_size: 64
timeout: 30.0
normalize: false
multitenant: false
```

`base_url` doit contenir le préfixe API, généralement `/v1`. Les URLs avec
credentials, query string ou fragment sont refusées afin que les erreurs ne
puissent pas exposer de secret. `api_key: local-dev` est une valeur locale non
secrète destinée aux runtimes qui exigent un header. Pour un endpoint protégé,
laisser la valeur hors Git et résoudre `adapters.embedding.api_key` avec la
capability [secrets](secrets.md). Ne jamais passer une clé de production au
scaffold pour l'écrire dans le YAML.

### Hôte Et Conteneur

- processus lancé sur l'hôte : `http://127.0.0.1:1234/v1` ;
- conteneur Docker Desktop macOS/Windows vers l'hôte :
  `http://host.docker.internal:1234/v1` ;
- Linux ou Kubernetes : utiliser une route explicitement configurée, un service
  DNS ou un endpoint réseau autorisé ; ne pas supposer que
  `host.docker.internal` existe.

Tous les runtimes locaux OpenAI-compatible pour le chat n'exposent pas
forcément `/v1/embeddings`, et tous les modèles ne savent pas produire des
embeddings. Vérifier les deux capacités dans l'interface ou la documentation du
runtime avant le smoke.

### Smoke Manuel Optionnel

Ce smoke vérifie le protocole sans faire partie des tests automatisés :

```bash
curl --fail-with-body \
  http://127.0.0.1:1234/v1/embeddings \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer local-dev' \
  -d '{"input":["smoke local"],"model":"nom-exact-du-modele-local","dimensions":768}'
```

Les tests Arclith utilisent un transport HTTP simulé. Ils ne nécessitent ni
réseau, ni LM Studio, ni Ollama. L'adapter découpe les sous-batches, réordonne
les résultats selon l'index provider, agrège l'usage, vérifie chaque dimension
et traduit auth, rate limit, timeout et indisponibilité vers les erreurs
communes. `normalize` vaut `false` quand le champ est omis. Avec
`normalize: true`, l'adapter applique une normalisation L2 locale ; avec
`false`, il conserve exactement les vecteurs du provider.

## Adapter OpenAI Officiel

`openai` appelle l'API Embeddings officielle sur `POST /v1/embeddings`. Il
réutilise l'extra HTTP optionnel `arclith[embedding]` et n'ajoute pas le SDK
OpenAI à l'installation minimale.

La documentation OpenAI consultée lors de cette implémentation expose notamment
`text-embedding-3-small` et `text-embedding-3-large`. Le catalogue CLI ne choisit
cependant aucun modèle à la place du service : vérifier les [modèles
d'embedding disponibles](https://developers.openai.com/api/docs/models/all) et
les droits du projet OpenAI, puis passer l'identifiant voulu explicitement.

```bash
uv add 'arclith[embedding]>=0.24.0'
arclith-cli add-adapter \
  --capability embedding \
  --adapter openai \
  --param model_name=remplacer-par-model-id-openai-embedding \
  --yes
```

Cette forme laisse le modèle choisir sa dimension native. Pour aligner
explicitement une collection vectorielle déjà dimensionnée, ajouter par
exemple `--param dimensions=1536`; le YAML généré contiendra alors
`dimensions: 1536` au lieu de `null`.

La configuration générée garde le secret hors Git :

```yaml
# config/adapters/outbound/embedding.yaml
adapter: openai
base_url: https://api.openai.com/v1
api_key: null
model_name: remplacer-par-model-id-openai-embedding
dimensions: null
batch_size: 64
timeout: 30.0
encoding_format: float
normalize: false
multitenant: false
```

```yaml
# config/secrets.yaml
resolver: env
mappings:
  adapters.embedding.api_key: OPENAI_API_KEY
```

Définir `OPENAI_API_KEY` dans l'environnement du processus, un secret
Kubernetes ou Vault. Ne jamais écrire la valeur dans le YAML versionné ni la
passer dans une commande conservée par l'historique du shell. Une absence de
clé résolue provoque une `EmbeddingAuthenticationError` actionnable avant tout
appel réseau.

Conformément à la [référence Create
embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create),
l'adapter envoie `input`, `model`, `encoding_format: float` et `dimensions`
uniquement quand cette dernière est configurée. Il réordonne les résultats par
`index` et expose `prompt_tokens`/`total_tokens` quand l'API les retourne. Le
champ provider `user` n'est pas alimenté automatiquement : un service ne doit
pas transmettre d'identifiant utilisateur brut sans décision explicite de
confidentialité.

Quand `dimensions` vaut `null`, l'adapter conserve la dimension renvoyée par le
modèle et vérifie qu'elle reste cohérente sur tous les sous-batches. Quand elle
est renseignée, toute différence déclenche `EmbeddingDimensionMismatch`. La
collection vectorielle cible doit être créée avec exactement la même dimension.

Les réponses 401/403, 429, les timeouts et les erreurs provider sont traduits
vers les exceptions communes sans reprendre la clé, le texte source ou le
payload dans le message. Les tests automatisés utilisent exclusivement
`httpx.MockTransport`; aucun appel à OpenAI n'est effectué par la suite de
tests.

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
Dans ce cas, `adapter` accepte le nom non vide déclaré par l'application ; le
registry valide ce nom à l'assemblage et retourne une erreur claire s'il n'est
pas enregistré :

```python
from arclith import EmbeddingRegistry

registry = EmbeddingRegistry().register("project", build_project_embedding)
embedding = app.embedding(registry=registry)
```

La configuration scoped associée contient alors `adapter: project`.

## Dimension Et Normalisation

La dimension configurée doit être identique à celle de la collection du
vector-store. Cette vérification doit avoir lieu à l'assemblage ou avant la
première écriture ; tronquer ou compléter silencieusement un vecteur rendrait
l'index incohérent.

Avec `normalize: true`, les adapters `deterministic` et `openai-compatible`
appliquent une normalisation L2 locale. Les providers peuvent déjà retourner
des vecteurs normalisés ou proposer leur propre option. Le service doit
documenter la métrique de distance choisie avec le vector-store et ne pas
supposer que tous les providers ont la même stratégie.

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
  tests/units/adapters/outbound/test_openai_compatible_embedding.py \
  tests/units/adapters/outbound/test_openai_embedding.py \
  tests/units/infrastructure/test_embedding_factory.py
uv run --project cli pytest cli/tests/test_embedding_capability.py
make docs
```

Le smoke doit vérifier la dimension et l'ordre des résultats. La stabilité
concerne uniquement `deterministic` ; la pertinence sémantique et la
disponibilité du modèle appartiennent au runtime provider.
