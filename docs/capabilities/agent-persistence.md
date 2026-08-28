# Capability Agent Persistence

## Intention

`agent-persistence` ajoute la persistance LangGraph sans coupler le domaine Arclith à LangGraph :

- le **checkpointer** conserve l'état d'un thread entre plusieurs runs ;
- le **store** conserve des mémoires partagées entre plusieurs threads.

La capability complète [agent/langgraph](agent.md). Elle ne remplace ni un repository métier ni une
base de données applicative.

## Position Hexagonale

La configuration appartient à l'adapter inbound LangGraph. Les nodes continuent d'appeler des ports
inbound ou des use cases ; ils ne reçoivent jamais un repository concret par cette capability.

## Quickstart

Créer d'abord le graphe, puis enrichir sa configuration :

```bash
arclith-cli add-adapter --capability agent --adapter langgraph --yes
arclith-cli add-adapter \
  --capability agent-persistence \
  --adapter langgraph \
  --param checkpointer=memory \
  --param store=memory \
  --yes
uv sync
```

Le CLI conserve les champs déjà présents dans `config/adapters/inbound/langgraph.yaml` et ajoute les
extras requis à la dépendance `arclith[...]` du projet. `memory` est réservé au développement et aux
tests : son contenu disparaît avec le processus.

## Formation

Le [quickstart Agent](../quickstarts/agent.md) construit le premier graphe. La page
[Validation IA locale](../learning/local-ai-validation.md) montre ensuite comment reprendre et
inspecter un thread par l'API Agent Server.

## Contrat

Configuration complète :

```yaml
# config/adapters/inbound/langgraph.yaml
persistence:
  enabled: true
  mode: auto # auto | embedded | agent_server
  checkpointer:
    adapter: memory # none | memory | sqlite | postgresql | mongodb | custom
    setup: false
    ttl_seconds: null
  store:
    adapter: memory # none | memory | postgresql | mongodb | redis | custom
    setup: false
    namespace_template: "{tenant_id}:{user_id}:memories"
    semantic_search:
      enabled: false
      embed: null
      dims: null
      fields: ["$"]
```

Le graphe peut activer explicitement le wiring :

```python
agent = arclith.langgraph(
    AgentState,
    register_agent,
    name="support_agent",
    persistence=True,
)
```

Si `persistence` est omis, `persistence.enabled: true` active aussi le wiring. Les priorités sont :

1. `checkpointer=...` et `store=...` explicites ;
2. configuration Arclith si la persistence est active ;
3. `None`, soit le comportement historique sans capability.

`persistence=False` désactive toute injection du framework, sans supprimer les objets fournis
explicitement. Fermer les connexions embedded à l'arrêt du processus :

```python
arclith.close_langgraph_persistence()
```

Construire un namespace store sans recopier le template :

```python
namespace = arclith.langgraph_memory_namespace(
    tenant_id=tenant_id,
    user_id=user_id,
)
# (tenant_id, user_id, "memories")
```

## Adapters

| Rôle | Adapter | Extra | Usage |
|---|---|---|---|
| checkpointer | `memory` | `langgraph` | dev/test volatile |
| checkpointer | `sqlite` | `langgraph-persistence-sqlite` | debug local reproductible |
| checkpointer + store | `postgresql` | `langgraph-persistence-postgresql` | production relationnelle |
| checkpointer + store | `mongodb` | `langgraph-persistence-mongodb` | production documentaire |
| store | `redis` | `langgraph-persistence-redis` | mémoire partagée Redis |
| les deux | `custom` | dépend du projet | factory importée ou registry |

Exemple SQLite :

```yaml
checkpointer:
  adapter: sqlite
  path: .arclith/langgraph-checkpoints.sqlite
```

Exemple PostgreSQL, sans credential dans Git :

```yaml
checkpointer:
  adapter: postgresql
  connection_uri_env: POSTGRESQL_URL
  setup: true
store:
  adapter: postgresql
  connection_uri_env: POSTGRESQL_URL
  setup: true
```

`setup: true` applique les tables/indexes fournis par l'intégration LangGraph. En production, les
migrations peuvent être exécutées séparément puis `setup` laissé à `false`.

## Extension Custom

Une factory importée reçoit les settings de son rôle et retourne un objet ou un context manager
synchrone :

```yaml
checkpointer:
  adapter: custom
  factory: "app.infrastructure.agent_memory:build_checkpointer"
```

Une registry permet aussi un nom de backend propre au projet :

```python
from arclith import LangGraphPersistenceRegistry

registry = LangGraphPersistenceRegistry().register_store("dynamodb", build_store)

agent = arclith.langgraph(
    AgentState,
    register_agent,
    persistence=True,
    persistence_registry=registry,
)
```

Les context managers asynchrones sont destinés à l'Agent Server, qui en gère le cycle de vie via
`langgraph.json`. Le mode embedded attend des composants synchrones.

## Production

`mode: auto` laisse l'Agent Server gérer checkpointer et store quand son runtime est détecté ; sinon,
Arclith construit les composants embedded. Forcer le choix avec `mode` ou, au runtime,
`ARCLITH_LANGGRAPH_PERSISTENCE_MODE=embedded|agent_server`.

Points à respecter :

- Agent Server injecte lui-même ses backends : ne pas compiler le graphe avec une seconde connexion ;
- MongoDB Agent Server exige un replica set ou un `mongos`, jamais un `mongod` standalone ;
- PostgreSQL utilise `thread_id` comme clé fréquente : préférer un UUID ou un hash court et stable ;
- les URI restent dans l'environnement runtime, `.env` non commité ou la capability `secrets` ;
- activer `LANGGRAPH_STRICT_MSGPACK=true` quand les checkpoints peuvent être compromis ;
- la recherche sémantique nécessite `embed`, `dims` et un backend/index compatible.

Pour l'Agent Server, PostgreSQL est le backend géré par défaut. MongoDB se configure dans
`langgraph.json` avec `checkpointer.backend: mongo` et `LS_MONGODB_URI` au runtime. Un checkpointer ou
store custom Agent Server est un async context manager référencé par `checkpointer.path` ou
`store.path`.

### Runtime Durable Open Source

Arclith fournit aussi `arclith-agent-runtime`, un serveur autonome destiné aux déploiements qui ne
disposent pas de `LANGGRAPH_CLOUD_LICENSE_KEY`. Il ne requiert ni clé LangGraph Cloud ni clé
LangSmith. `LANGSMITH_API_KEY` reste une intégration d'observabilité optionnelle et indépendante.

Installer puis sélectionner le runtime dans l'image standard :

```bash
uv add "arclith[langgraph,langgraph-runtime]"
ARCLITH_AGENT_RUNTIME=durable ./arclith-run agent
```

Variables requises :

| Variable primaire | Alias accepté | Contenu |
|---|---|---|
| `DATABASE_URI` | `POSTGRESQL_URL` | URI PostgreSQL du runtime |
| `REDIS_URI` | `REDIS_URL` | URI Redis de coordination |

Le runtime charge les graphes de `langgraph.json`, force le mode de persistance `agent_server` à
l'import, puis attache un `AsyncPostgresSaver` et un `AsyncPostgresStore` sur un pool partagé. Il
ajoute un catalogue PostgreSQL pour les métadonnées de threads et de runs. Redis ne contient pas la
conversation : il fournit un verrou distribué par thread et les demandes d'annulation, avec une
expiration de sécurité. Le verrou est renouvelé pendant le run et expire en 30 secondes par défaut
si un pod disparaît sans arrêt gracieux.

Surface HTTP compatible avec les usages Jarvis et le SDK LangGraph :

- assistants : recherche et lecture ;
- threads : création, recherche, lecture, suppression, état et historique ;
- runs : attente, streaming SSE, liste, lecture et annulation ;
- streaming : événements `metadata`, `values`, `custom` et `messages` ;
- reprise : `checkpoint`, `checkpoint_id` et `command` LangGraph.

Cette surface n'est pas une réimplémentation exhaustive de la plateforme LangGraph. Les crons,
déploiements, revisions d'assistants, webhooks, double-texting autre que `reject` et services
LangSmith ne sont pas fournis. `/info` annonce explicitement ces limites.

Garde-fous de production :

- une base ou un schéma isolé par agent/trust boundary ;
- un utilisateur PostgreSQL dédié, autorisé à créer les tables au premier démarrage ;
- un utilisateur Redis et `ARCLITH_LANGGRAPH_REDIS_PREFIX` dédiés ;
- une NetworkPolicy limitant les flux aux seuls PostgreSQL et Redis ;
- `terminationGracePeriodSeconds` supérieur à `ARCLITH_GRACEFUL_TIMEOUT_SECONDS` ;
- sauvegarde PostgreSQL vérifiée par restauration, Redis restant reconstructible ;
- aucun URI ni message d'exception interne écrit dans la réponse SSE.

Le schéma est créé de façon idempotente au démarrage. Pour une gouvernance DDL séparée, exécuter une
première initialisation avec un rôle propriétaire, puis lancer les pods avec
`ARCLITH_LANGGRAPH_AUTO_SETUP=false` après avoir retiré les privilèges de création au rôle runtime.

## Validation

En embedded, deux appels avec le même `thread_id` doivent reprendre le même état :

```python
config = {"configurable": {"thread_id": "018f-stable-thread"}}
agent.invoke({"messages": ["premier message"]}, config)
agent.invoke({"messages": ["suite"]}, config)
```

Avec l'Agent Server :

```bash
THREAD_ID=$(curl -fsS -X POST http://127.0.0.1:2024/threads \
  -H 'Content-Type: application/json' -d '{}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
```

Un test store doit écrire une mémoire sous `(tenant_id, user_id, "memories")`, puis la relire depuis
un second `thread_id`.

## Troubleshooting

| Erreur | Action |
|---|---|
| `Backend ... non installe` | installer l'extra indiqué puis exécuter `uv sync` |
| variable `POSTGRESQL_URL`, `MONGODB_URI` ou `REDIS_URL` requise | injecter le secret au runtime |
| état absent au second run | vérifier `configurable.thread_id` et sa stabilité |
| aucun objet injecté sous Agent Server | comportement attendu : le serveur fournit ses backends |
| `setup()` asynchrone en embedded | utiliser une implémentation sync ou le mode Agent Server |
| `/ready` retourne `503` | vérifier PostgreSQL, Redis, credentials et NetworkPolicy |
| second run refusé avec `409` | un run est déjà actif pour ce `thread_id` |
| état présent mais thread absent | ne pas écrire directement dans les tables du checkpointer ; créer le thread via l'API |

## Projet

Lire [agent/langgraph](agent.md), [Lancement local Agent](../runtime-docker/local-agent.md), puis le
[parcours Todo agent](../tutorials/todo-list/06-agent.md).

## Sources

- [Persistence LangGraph](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Checkpointer integrations](https://docs.langchain.com/oss/python/integrations/checkpointers)
- [Store integrations](https://docs.langchain.com/oss/python/integrations/long-term-memory)
- [Agent Server](https://docs.langchain.com/langsmith/agent-server)
- [Custom checkpointer](https://docs.langchain.com/langsmith/custom-checkpointer)
- [Custom store](https://docs.langchain.com/langsmith/custom-store)
