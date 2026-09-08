# Blueprints Complets Des Adapters

Le scaffold crée immédiatement l'organisation complète de la technologie choisie,
y compris les rôles qui ne sont pas encore utilisés. Chaque package possède
`__init__.py` et `README.md`, chaque rôle de module possède un fichier Python
importable. Les développeurs et les IA disposent ainsi du même rangement avant
de commencer une fonctionnalité.

## Contrat Et Propriété

`ProjectLayout.scaffold_directories()` définit les packages du projet.
`arclith_cli.adapter_blueprints.get_adapter_blueprint()` fournit le contrat versionné
de chaque adapter du catalogue. Les templates exécutables sont des ressources
distribuées dans le wheel CLI sous `templates/adapters/`.

`init` installe les layouts complets FastAPI et FastMCP présents dans ses dépendances.
`add-adapter` installe tous les rôles de la technologie sélectionnée. `new` conserve
l'application CRUD du sample officiel et lui applique le même contrat de dossiers.
Il reste un parcours basé sur le sample, et n'est pas assimilé à `init` plus une
recipe de génération métier.

`add-entity` prépare également immédiatement la feature complète de cette entité
dans les adapters FastAPI/FastMCP déjà installés. Les modules de contrat, mapping,
présentation, routes, tools, resources et prompts existent avant le premier binding.
Cela n'enregistre aucune opération publique et ne remplace pas un contrat personnalisé.

```bash
arclith-cli add-adapter --capability agent --adapter langgraph --yes --dry-run
arclith-cli add-adapter --capability agent --adapter langgraph --yes
```

Le dry run affiche le plan sans écrire de fichier ni de recipe. Une relance remplit
les fichiers manquants et conserve les fichiers développeur existants. Les fichiers
`*_generated.py` sont explicitement possédés par le CLI et régénérés ; les fichiers
de composition développeur les utilisent comme points d'extension. Les paramètres
de configuration demandés restent gérés par le catalogue.

`.arclith/blueprints/<capability>-<adapter>.yaml` enregistre la version du blueprint
et son digest SHA-256. Ce digest décrit les templates à l'installation ; il ne
certifie pas le contenu des fichiers que le développeur a ensuite modifiés.

## Frontière Applicative

```text
Transport DTO -> mapper -> Command/Query typée -> port inbound -> use case
                                             <- Result <- presenter
```

La composition des dépendances concrètes vit dans `infrastructure`. Un adapter
inbound n'importe jamais un repository concret. Les commandes applicatives ne
contiennent pas de headers HTTP, d'enveloppe RabbitMQ ou de types LangGraph.
`contracts/` contient les contrats de transport et leurs traductions ; leur
stabilité est indépendante de celle des modèles applicatifs.

## FastAPI

```text
fastapi/
  register.py
  dependencies.py
  errors.py
  contracts/
  middleware/
  routers/
    v1/
      router.py
      <feature>/
        router.py
        schemas.py
        mappers.py
        presenters.py
        openapi.py
        routes/
```

Chaque route déclare ses statuts et réponses. `register.py` inclut le router de
version, qui compose explicitement les routers de fonctionnalité. Aucun endpoint
métier n'est inventé par le blueprint.
[Référence FastAPI](https://fastapi.tiangolo.com/tutorial/bigger-applications/).

## FastMCP

```text
fastmcp/
  register.py
  dependencies.py
  errors.py
  contracts/
  middleware/
  features/
    <feature>/
      register.py
      schemas.py
      mappers.py
      presenters.py
      tools/
      resources/
      prompts/
```

Les trois primitives MCP sont présentes dès l'installation. Elles sont enregistrées
explicitement, sans découverte par effet de bord d'import. Les entités déjà connues
fournissent les noms de features ; sinon le package `example` sert de repère inerte.
[Référence FastMCP](https://gofastmcp.com/servers/composition).

## LangGraph

```text
langgraph/
  agent.py
  graph.py
  state.py
  context.py
  dependencies.py
  routing.py
  nodes/
    example.py
  contracts/
  capabilities/
  subgraphs/
  tools/
  prompts/
  parsers/
  presenters/
  policies/
  persistence/
  shared/
```

`agent.py` est la façade stable pour `langgraph.json`. `graph.py` montre la topologie
et reçoit l'instance Arclith du processus. Les nodes retournent des patches et
ne réémettent pas toute la liste des messages, qui possède un reducer. `AgentContext`
porte les informations d'invocation non persistées ; `AgentState` porte un
`state_version` et les messages sérialisables.

Les fonctions métier portables restent dans l'application. Une capability regroupe
un comportement conversationnel ; un subgraph est un véritable graphe compilé avec
plusieurs nodes et une frontière d'état/cycle de vie justifiée. Les changements de
clés persistées exigent des tests de compatibilité et de reprise.

`shared/` accueille uniquement des primitives utilisées par au moins deux
capabilities. Éviter les modules globaux `nodes.py`, `utils.py`, `helpers.py`.
[Référence LangGraph](https://docs.langchain.com/oss/python/langgraph/application-structure).

## RabbitMQ Et Autres Familles

| Capability | Packages créés immédiatement | Modules racine |
|---|---|---|
| command-bus | bindings, contracts, schemas, policies | register, codec, topology, consumer, publisher, dependencies |
| channel | inbound, outbound, schemas, mappers, presenters, attachments, policies | register, client, dependencies, security, errors |
| repository | repositories, models, mappers, indexes, migrations | dependencies, errors |
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
| agent-persistence | persistence/checkpoints, persistence/stores, persistence/migrations | — |
| observability | instrumentation, exporters, sampling | setup, correlation, dependencies |
| runtime | bootstrap, health, policies | settings, lifecycle |

Les providers restent des dossiers de technologie dans la couche existante. Les
noms contenant un tiret sont normalisés en underscore pour être importables. Quand
une technologie sert plusieurs capabilities, leurs rôles sont ajoutés au même
package sans écraser les implémentations déjà présentes. Le runtime conteneur vit
dans `infrastructure/runtime/docker_image` et conserve ses fichiers Docker à la racine.

Les repositories créés de façon incrémentale obtiennent aussi leur port outbound,
service standard et fallback memory s'ils manquent. Chaque entité possède son
module de repository. Le fichier historique `repository.py` conserve les imports
des différentes entités. Le registre `*_registrations_generated.py` est séparé
du container personnalisable.

## Validation

La suite teste le rendu et la syntaxe Python pour chaque adapter du catalogue,
l'idempotence, la conservation des personnalisations, le dry run, les imports des
repositories multi-entités et l'invocation du graphe généré. Le groupe `dev` du
CLI déclare les extras Arclith `fastapi`, `mcp` et `langgraph` : ces tests runtime
sont obligatoires, avec les mêmes dépendances verrouillées en local et en CI
(`cd cli && uv sync --frozen --group dev && uv run --frozen pytest`).

`validate_adapter_blueprint(root, blueprint)` signale les fichiers natifs absents.
Cette validation vérifie l'organisation ; les tests applicatifs et de contrats
doivent vérifier les comportements de chaque route, tool, node et binding.
