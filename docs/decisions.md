# docs/decisions.md — Arclith (`arclith`)

## ADR-001 — UUIDv7 comme identifiant d'entité

**Contexte :** Choix de l'algorithme d'ID pour les entités.

**Décision :** UUIDv7 via la bibliothèque `uuid6`.

**Pourquoi pas l'alternative évidente (UUIDv4) :**
UUIDv4 est aléatoire — pas d'ordre temporel, ce qui dégrade les index B-tree (MongoDB, DuckDB) et rend le tri par ID
impossible. UUIDv7 est ordonné par le temps à la milliseconde, combine les avantages d'un ULID et d'un UUID standard.

**Conséquence sur le code :**

- `Entity.uuid` est de type `uuid6.UUID`, pas `uuid.UUID` stdlib.
- Les adaptateurs MongoDB stockent l'UUID en string pour compatibilité.
- `@field_validator("uuid", mode="before")` sur `Entity` coerce automatiquement les strings en `UUID`.

---

## ADR-002 — Pydantic v2 comme système de modèles

**Contexte :** Validation et sérialisation des entités et de la config.

**Décision :** Pydantic v2 (`pydantic==2.x`), `BaseModel` avec `ConfigDict`.

**Pourquoi pas l'alternative évidente (dataclasses stdlib) :**
Les dataclasses n'ont pas de validation automatique des types à l'instanciation, pas de sérialisation JSON intégrée, pas
de `field_validator`. Pydantic v2 offre la validation au runtime et est le standard de l'écosystème FastAPI.

**Conséquence sur le code :**

- `Entity` étend `BaseModel`, pas `dataclass`.
- `model_config = ConfigDict(arbitrary_types_allowed=True)` pour accepter `uuid6.UUID`.
- Les `@field_validator` utilisent `mode="before"` pour la coercion.

---

## ADR-003 — Soft-delete par champ `deleted_at`

**Contexte :** Suppression logique des entités sans perte de données.

**Décision :** Champ `deleted_at: datetime | None` sur `Entity`. Suppression physique différée via `PurgeUseCase` selon
`retention_days`.

**Pourquoi pas l'alternative évidente (champ booléen `is_deleted`) :**
Un booléen ne porte pas d'information temporelle. `deleted_at` permet de calculer le délai de rétention sans champ
supplémentaire et de trier les suppressions par date.

**Conséquence sur le code :**

- `find_all()` filtre automatiquement les entités où `deleted_at is not None`.
- `find_deleted()` retourne uniquement les supprimées.
- `PurgeUseCase` supprime physiquement celles dont `deleted_at + retention_days < now`.
- `retention_days: null` = conservation infinie ; `0` = suppression immédiate (pas de soft-delete).

---

## ADR-004 — Optimistic locking via champ `version`

**Contexte :** Prévenir les écritures concurrentes conflictuelles.

**Décision :** Champ `version: int = 1` incrémenté à chaque `update`.

**Pourquoi pas l'alternative évidente (pessimistic locking / transactions) :**
Les transactions MongoDB ont un surcoût significatif. L'optimistic locking est suffisant pour les volumes cibles et
évite les deadlocks dans un contexte async.

**Conséquence sur le code :**

- Les adaptateurs `update()` doivent incrémenter `version` avant persistance.
- Les clients qui soumettent une version obsolète recevront un conflit (à implémenter dans les use cases si nécessaire).

---

## ADR-005 — DuckDB comme adaptateur fichier plutôt que SQLite

**Contexte :** Persistance légère sans serveur pour le dev et les sandboxes.

**Décision :** DuckDB via `duckdb==1.5.0`, formats supportés : `.csv`, `.parquet`, `.json`, `.arrow`.

**Pourquoi pas l'alternative évidente (SQLite) :**
DuckDB est orienté analytique et supporte nativement Parquet, Arrow et CSV sans ORM. Il est plus adapté à des exports de
données et à la lecture de fichiers plats. SQLite nécessiterait un ORM ou du SQL manuel.

**Conséquence sur le code :**

- `DuckDBSettings.path` valide l'extension : seuls `.csv`, `.parquet`, `.json`, `.arrow` sont acceptés (ou un dossier).
- `DuckDBRepository[T]` reconstruit les entités depuis les colonnes du fichier.
- Pas de migrations : le schéma est inféré depuis le modèle Pydantic.

---

## ADR-007 — Suppression du transport MCP stdio

**Date :** 2026-03-28

**Contexte :** `arclith` exposait trois transports MCP : stdio, SSE et streamable-HTTP. Le transport stdio est
fondamentalement incompatible avec un déploiement Kubernetes (il repose sur stdin/stdout d'un subprocess local) et ne
supporte pas les headers HTTP, rendant toute authentification JWT impossible.

**Décision :** supprimer `run_mcp_stdio()` de `Arclith`.

**Pourquoi pas l'alternative (garder stdio pour usage local) :**
Garder du code mort augmente la surface de test et introduit une confusion : les développeurs pourraient croire que le
transport stdio est supporté en production. Le debug local passe par HTTP (127.0.0.1) avec les mêmes outils.

**Conséquence sur le code :**

- `Arclith.run_mcp_stdio()` supprimé.
- `main_mcp_stdio.py` ne doit plus être créé dans les repos consommateurs.
- Seuls `run_mcp_sse()` et `run_mcp_http()` sont conservés.

---

## ADR-008 — Pipeline d'authentification JWT mutualisé FastAPI / FastMCP

**Date :** 2026-03-28

**Contexte :** FastAPI et FastMCP ont fondamentalement le même besoin : extraire un Bearer token, le valider via
Keycloak JWKS, vérifier la licence, résoudre le tenant. La seule différence est la façon d'accéder aux headers HTTP
(`Request` vs `fastmcp.Context`).

**Décision :** extraire le cœur du pipeline dans `adapters/inbound/auth_pipeline.py` → `run_auth_pipeline(headers, ...)`.
Les adapters FastAPI et FastMCP sont de simples wrappers qui extraient les headers selon leur transport puis appellent
`run_auth_pipeline`. Signatures identiques pour `make_inject_tenant_uri`.

**Pourquoi pas l'alternative (deux implémentations séparées) :**
La logique dupliquée crée une dérive inévitable. Un bugfix ou une évolution (nouveau claim, nouveau type de resolver)
devrait être appliqué deux fois.

**Conséquence sur le code :**

- `auth_pipeline.py` : unique source de vérité pour la logique JWT.
- `fastapi/dependencies.py` et `fastmcp/dependencies.py` : wrappers ~10 lignes.
- `fastapi/auth.py` et `fastmcp/auth.py` : protection sélective opt-in (par route ou par tool).
- `Arclith.auth_dependency(transport)` : factory qui construit le bon `require_auth` depuis la config.
- Tests du pipeline mutualisé : un seul fichier `tests/units/adapters/inbound/test_auth_pipeline.py` (à créer — SK-AUTH-01).


---

## ADR-009 — `ws="websockets-sansio"` imposé sur toutes les configs uvicorn

**Date :** 2026-04-04

**Contexte :** `uvicorn 0.41.0` sélectionne automatiquement `websockets_impl.py` (legacy) quand `websockets` est installé
(via `fastmcp`). Ce module importe `websockets.legacy`, déprécié depuis `websockets 14.0`. `fastmcp/__init__` active
globalement `warnings.simplefilter("default", DeprecationWarning)`, rendant le warning visible à chaque démarrage.

**Décision :** Passer `ws="websockets-sansio"` explicitement à chaque construction de `uvicorn.Config` / `uvicorn.run()`
dans `arclith`. L'implémentation `websockets_sansio_impl.py` n'utilise que la nouvelle API `websockets` (≥14.0), sans
import `legacy`.

**Pourquoi pas l'alternative évidente (supprimer le warning via `filterwarnings`) :**
Masquer un avertissement sans corriger la cause racine est interdit : cela cache une dette technique et peut dissimuler
des régressions futures. **Règle absolue : on ne masque jamais un warning sans corriger sa source.**

**Pourquoi pas bump de `uvicorn` :**
Avant tout bump de dépendance, il faut vérifier quelle version exacte corrige le comportement ciblé (règle SK-F10).
Ici, `ws="websockets-sansio"` est disponible depuis uvicorn 0.20+, la correction est déterministe et ne nécessite
aucun changement de contrainte dans `pyproject.toml`.

**Conséquence sur le code :**

- `Arclith.run_api()` — `uvicorn.run(..., ws="websockets-sansio")`
- `ProbeServer.start_in_background()` — `uvicorn.Config(..., ws="websockets-sansio")`
- `websockets_impl.py` (legacy) n'est jamais chargé par arclith.

---

## ADR-010 — Layout hexagonal inbound/outbound et adapters enregistrables

**Date :** 2026-08-03

**Contexte :** Arclith doit devenir une base générique pour des microservices et agents qui pourront
utiliser FastAPI, FastMCP, LangGraph, Pydantic AI ou d'autres frameworks. Le coeur applicatif ne doit
jamais dépendre de ces adapters. Côté persistence, MongoDB est déjà disponible, mais d'autres adapters
comme MariaDB, PostgreSQL ou des event stores doivent pouvoir être ajoutés sans modifier le framework.

**Décision :** formaliser le vocabulaire hexagonal cible:

- `domain/ports/inbound` pour les capacités exposées par le coeur;
- `domain/ports/outbound` pour les dépendances appelées par le coeur;
- `adapters/inbound` pour HTTP, MCP, CLI, workers, agents;
- `adapters/outbound` pour repositories, LLM, cache, secrets, events.

Les anciens noms `input` et `output` ne sont pas conservés: Arclith est encore en phase
initiale et cette refonte choisit une rupture nette plutôt qu'une compatibilité temporaire.
Les adapters de repositories ne sont plus sélectionnés par un `match` central fermé: ils passent par un
`RepositoryRegistry` avec adapters built-in enregistrés par défaut.

**Pourquoi pas l'alternative évidente (ajouter MariaDB dans le switch existant) :**
Un switch central oblige Arclith à connaître chaque adapter concret. Cela casse l'extension naturelle
du framework, mélange le coeur d'assemblage et les drivers, et recrée de la dette à chaque nouvelle
technologie.

**Conséquence sur le code :**

- `AdaptersSettings.repository` accepte un nom libre.
- `build_repository(..., registry=...)` peut recevoir un registry applicatif.
- `Arclith.repository(..., registry=...)` expose ce point d'extension.
- `ProjectLayout` expose uniquement les chemins canoniques inbound/outbound.
- Les futurs adapters MariaDB/PostgreSQL peuvent être livrés comme packages ou modules séparés.

---

## ADR-011 — LangSmith Studio comme banc de test agent

**Date :** 2026-08-05

**Contexte :** Arclith doit servir de base commune pour des services exposes par API, MCP ou agents.
Le coeur applicatif enregistre des donnees deterministes via des cas d'usage; l'agent traduit une
intention en commande structuree a la frontiere. Le POC todo a montre qu'une UI dediee n'est pas
necessaire si LangGraph Studio et LangSmith couvrent les tests conversationnels et les traces.

**Decision :** declarer le runtime agent comme une capacite inbound `agent`, avec un adapter
standard `langgraph`, et declarer l'observabilite agent comme une capacite outbound
`observability`, avec un adapter standard `langsmith`. La CLI genere le point d'entree LangGraph,
`langgraph.json` et le cablage `Arclith.langgraph(...)`. La configuration runtime reste nommee par
produit, comme `fastapi` et `fastmcp`: `config/adapters/inbound/langgraph.yaml` alimente
`AppConfig.langgraph`, sans cle generique `adapters.agent`. La CLI demande ensuite les informations
LangSmith au moment du `add-adapter`, genere `config/adapters/outbound/langsmith.yaml`, met a jour
`.env`, et ignore `.env` dans Git. LangSmith Studio devient l'endroit standard pour tester les
agents.

**Pourquoi pas l'alternative evidente (une UI de test generee par Arclith) :**
Une UI de test serait une surface produit supplementaire a maintenir, sans porter le metier. Elle
dupliquerait les fonctions de LangSmith Studio: execution locale, conversation, traces, inspection et
debug agent. Arclith doit plutot standardiser le branchement et laisser l'outil specialise porter les
tests agent.

**Consequence sur le code :**

- `CapabilitySpec` supporte les adapters non scopes par entite et les templates `.env`.
- `arclith-cli add-adapter --capability agent --adapter langgraph` genere l'entrypoint agent
  inbound et laisse le code specifique dans `src/<package>/adapters/inbound/langgraph/agent.py`.
- `config/adapters/inbound/langgraph.yaml` est charge dans `AppConfig.langgraph`, sur le meme
  principe produit que `fastapi` et `fastmcp`.
- `arclith-cli add-adapter --capability observability --adapter langsmith` demande les parametres
  LangSmith et n'essaie pas de generer un repository par entite.
- `AdaptersSettings.observability` active l'observabilite sans coupler le coeur aux SDK agent.
- `Arclith.langgraph(...)` standardise la creation et la compilation du graphe sans exposer cette
  plomberie a chaque projet.
- Le serveur LangGraph local lit `.env` via le `langgraph.json` genere.

---

**Contexte :** Exposer les services via le Model Context Protocol.

**Décision :** `fastmcp>=3.1.0` avec trois transports : stdio, SSE, streamable-HTTP.

**Pourquoi pas l'alternative évidente (implémentation MCP manuelle) :**
FastMCP gère la sérialisation, le routing et les transports. Une implémentation manuelle serait fragile et ne suivrait
pas les évolutions du spec MCP.

**Conséquence sur le code :**

- `Arclith.fastmcp(name)` retourne un `FastMCP` instance.
- Les tools sont enregistrés via `@mcp.tool` (décorateur) à l'intérieur des classes `*MCP`.
- `run_mcp_sse()` et `run_mcp_http()` lisent `config.mcp.host` / `config.mcp.port`.
