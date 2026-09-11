# Contrat d'arborescence des adapters

Arclith applique un contrat fermé et versionné : une technologie n'apparaît dans
un projet qu'après `arclith-cli add-adapter`, et une feature publique n'apparaît
qu'après `arclith-cli expose-usecase`. `init`, `add-entity` et `add-usecase` ne
déduisent jamais un adapter ou une feature.

Le contrat a trois représentations synchronisées :

1. cette documentation officielle ;
2. les `README.md` générés à la racine de chaque adapter et de chaque rôle ;
3. `.arclith/blueprints/<capability>-<adapter>.yaml`, qui contient la version,
   le digest et la liste fermée `expected_paths`.

Le `AGENTS.md` d'un projet généré oblige les agents de codage à lire
`ARCHITECTURE.md` et le README le plus proche. Si une responsabilité ne rentre
dans aucun emplacement déclaré, on fait évoluer le blueprint, sa documentation
et ses tests avant de créer un nouveau chemin. Les répertoires génériques
`utils`, `helpers` et `common` sont interdits par défaut.

## Socle du projet

Le seul layout applicatif supporté est `src/<package>`. Le niveau `<package>` est
nécessaire : c'est le package Python distribué, tandis que `src/` empêche les
imports accidentels depuis le checkout.

```text
src/<package>/
├── domain/
│   ├── models/
│   ├── events/
│   ├── value_objects/
│   └── ports/{inbound,outbound}/
├── application/
│   ├── use_cases/
│   ├── services/
│   ├── workflows/
│   └── intent_interpreters/
├── adapters/{inbound,outbound,bidirectional}/
└── infrastructure/
    ├── use_cases_generated.py
    ├── containers/
    └── bootstrap/
```

`domain` porte le modèle et les ports, `application` les règles d'orchestration,
`adapters` les traductions de protocole/provider, et `infrastructure` la
composition concrète. Aucun adapter inbound n'importe un adapter outbound.

## Installation et propriété

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes --dry-run
arclith-cli add-adapter --capability api --adapter fastapi --yes
```

Le dry run ne modifie ni fichiers ni recette. Une relance restaure les éléments
manquants mais préserve les fichiers développeur. Seuls `*_generated.py` et les
manifests de binding sont possédés et régénérés par le CLI. Les `__init__.py`
restent sans effet de bord.

Les packages de rôle contiennent un `README.md` qui décrit leur responsabilité.
Les modules racine inertes servent de point d'extension nommé ; ils ne doivent
être implémentés que lorsqu'un besoin réel l'exige. Cette structure guidée évite
à la fois les dossiers anonymes et la création libre de fichiers.

## FastAPI

Après `add-adapter --capability api --adapter fastapi` :

```text
adapters/inbound/fastapi/
├── README.md
├── register.py
├── bindings_generated.py
├── dependencies.py
├── errors.py
├── contracts/
├── middleware/
└── routers/
    └── v1/
        └── router.py
```

Après l'exposition d'un use case dans la feature `todos` :

```text
routers/v1/todos/
├── README.md
├── router.py
├── schemas.py
├── mappers.py
├── presenters.py
├── openapi.py
└── routes/
    └── create_todo.py
```

La chaîne est unique : `main.build_api()` appelle `register.py`, qui inclut le
router v1 ; le router v1 appelle `bindings_generated.py`, qui construit chaque
router de feature et l'inclut une seule fois. Le chemin `/v1` appartient au
router de version et n'est donc jamais dupliqué dans la route d'opération.

Chaque route appelle un port inbound typé, déclare son statut, son
`response_model` de transport et ses erreurs publiques. Elle ne contient aucune
règle métier ni construction de repository.

## FastMCP

Après installation :

```text
adapters/inbound/fastmcp/
├── README.md
├── register.py
├── bindings_generated.py
├── dependencies.py
├── errors.py
├── contracts/
├── middleware/
└── features/
```

Après exposition dans `todos` :

```text
features/todos/
├── README.md
├── register.py
├── schemas.py
├── mappers.py
├── presenters.py
├── tools/create_todo.py
├── resources/
└── prompts/
```

Le binding généré est un tool car `expose-usecase` exprime une action. Les
packages `resources` et `prompts` restent des primitives MCP distinctes et
documentées ; le CLI n'invente aucun contenu. Tous appellent les mêmes ports
applicatifs que FastAPI.

## RabbitMQ

```text
adapters/bidirectional/rabbitmq/
├── README.md
├── register.py
├── bindings_generated.py
├── codec.py
├── topology.py
├── consumer.py
├── publisher.py
├── dependencies.py
├── bindings/<operation>.py
├── contracts/
├── schemas/
└── policies/
```

Le binding valide le payload puis appelle le port inbound. Les enveloppes,
confirmations de publication, ACK/NACK, retry et DLX restent dans l'adapter
framework. Les handlers doivent être idempotents lorsque la commande peut être
rejouée.

## Repository

```text
adapters/outbound/<provider>/
├── README.md
├── dependencies.py
├── errors.py
├── repositories/
├── models/
├── mappers/
├── indexes/
└── migrations/
```

Les providers intégrés (`memory`, `mongodb`, `duckdb`, `mariadb`, `postgresql`)
sont des implémentations génériques de `Repository[T]` fournies par Arclith.
Le composition root appelle `arclith.repository(Entity)` ; aucun repository par
entité, service standard, container ou fallback `memory` n'est généré dans le
projet. Choisir MongoDB ne crée donc que le blueprint MongoDB et sa configuration.

Un fichier projet sous `repositories/` n'est justifié que par un port outbound
custom, par exemple une recherche métier qui dépasse `Repository[T]`.
`models/`, `mappers/`, `indexes/` et `migrations/` restent les emplacements
obligatoires des détails provider correspondants.

## Autres capabilities

| Capability | Packages autorisés | Modules racine autorisés |
|---|---|---|
| storage | transfers, metadata, policies | client, dependencies, errors |
| vector-store | collections, mappers, indexes, migrations | client, dependencies, errors |
| cache | codecs, keys, invalidation, locks | client, dependencies, errors |
| logger | formatters, filters, sinks | setup, correlation |
| secrets | resolvers, rotation, policies | provider, settings, errors |
| probe | checks, diagnostics | register, health, readiness, dependencies |
| http | middleware, policies, schemas | register, dependencies, errors |
| auth | principals, mappers, policies | dependencies, errors |
| tenant | resolvers, mappers, policies | dependencies, context, errors |
| license | mappers, policies | dependencies, errors |
| llm | models, mappers, policies | client, dependencies, errors |
| embedding | models, mappers, batching, policies | client, dependencies, errors |
| channel | inbound, outbound, schemas, mappers, presenters, attachments, policies | register, client, dependencies, security, errors |
| observability | instrumentation, exporters, sampling | setup, correlation, dependencies |
| runtime | bootstrap, health, policies | settings, lifecycle |

## LangGraph

LangGraph conserve son contrat spécialisé : `agent.py`, `graph.py`, `state.py`,
`context.py`, `dependencies.py`, `routing.py`, puis `nodes`, `contracts`,
`capabilities`, `subgraphs`, `tools`, `prompts`, `parsers`, `presenters`,
`policies`, `persistence` et `shared`. `shared` est réservé aux primitives
réellement utilisées par au moins deux capabilities.

## Validation

La suite du CLI vérifie pour chaque entrée du catalogue : syntaxe Python,
présence de tous les chemins du blueprint, digest, idempotence, préservation des
fichiers développeur, absence de feature implicite et refus des collisions. Les
smokes end to end vérifient ensuite les bindings FastAPI, FastMCP, RabbitMQ et
les repositories à partir de projets neufs.
