# Quickstart agent Arclith from scratch

Ce guide part de zéro et aboutit à un service local qui expose:

- une entité métier `Ingredient`;
- une API FastAPI générée par `arclith-cli`;
- un agent LangGraph testé dans LangGraph Studio;
- des traces LangSmith;
- un LLM local LM Studio via endpoint OpenAI-compatible.

La règle d'architecture reste la même du début à la fin:

```text
Demande naturelle
  -> adapter inbound LangGraph
  -> planner LLM derrière configuration locale
  -> commande structurée
  -> service/use case métier
  -> repository de l'entité
```

Le LLM traduit l'intention. Il ne doit pas écrire directement dans la persistance.

## 1. Prérequis

- Python 3.13
- `uv`
- `git`
- LM Studio avec le Local Server démarré sur `http://127.0.0.1:1234/v1`
- un modèle chargé dans LM Studio
- une clé LangSmith si le tracing doit remonter dans LangSmith

Installer la CLI depuis le repository:

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
arclith-cli version
```

Pour tester une branche Arclith avant publication:

```bash
uv tool install --force \
  "git+https://github.com/karned-rekipe/arclith.git@<branche>#subdirectory=cli"
```

## 2. Créer l'entité et l'API

Le scaffold crée l'entité `Ingredient`, les ports, le service applicatif, l'API FastAPI, MCP et les
probes.

```bash
mkdir -p ~/Perso/projets/demo
cd ~/Perso/projets/demo

arclith-cli new Ingredient pantry-agent --port 8100
cd pantry-agent
uv sync
```

Le premier `uv sync` crée `uv.lock`. Ensuite, utiliser `uv run --frozen ...` pour vérifier que
l'environnement reste conforme au lockfile.

Lancer le service:

```bash
MODE=all uv run --frozen python main.py
```

Vérifier les probes et l'API:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:8100/docs
```

Créer une ressource par API structurée:

```bash
curl -fsS -X POST http://127.0.0.1:8100/v1/ingredients/ \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pantry-demo-1" \
  -d '{"name":"Farine de ble"}'
```

## 3. Ajouter LangGraph et LangSmith

Installer les dépendances agent dans le projet généré:

```bash
uv add "arclith[langgraph]"
```

Générer l'entrypoint LangGraph:

```bash
arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --param graph_name=pantry_agent \
  --yes
```

Générer la configuration LangSmith:

```bash
export LANGSMITH_API_KEY="<clé-langsmith>"

arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --param project=pantry-agent-dev \
  --param endpoint=https://api.smith.langchain.com \
  --param api_key="$LANGSMITH_API_KEY" \
  --yes
```

Résultat attendu:

```text
langgraph.json
config/adapters/inbound/langgraph.yaml
config/adapters/outbound/lm.yaml
config/adapters/outbound/langsmith.yaml
src/pantry_agent/application/planners/ingredient_intent.py
src/pantry_agent/adapters/inbound/langgraph/agent.py
.env
```

`langgraph.json` pointe vers `.env`; le serveur LangGraph local charge donc les variables
`LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` et `LANGSMITH_API_KEY`.

## 4. Configurer LM Studio et le planner

Dans LM Studio:

1. charger un modèle;
2. démarrer le Local Server;
3. relever l'identifiant exact du modèle.

Vérifier les modèles exposés:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Ajouter la configuration LLM Arclith:

```bash
arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id-lm-studio>" \
  --yes
```

`provider: openai` désigne ici le protocole OpenAI-compatible, pas forcément le fournisseur OpenAI.
Si LM Studio tourne sur la machine hôte et que l'agent tourne en container, remplacer souvent
`127.0.0.1` par `host.docker.internal`.

Créer le fichier minimal du planner applicatif:

```bash
arclith-cli add-planner IngredientIntent
```

Remplacer `src/pantry_agent/application/planners/ingredient_intent.py` par:

```python
from typing import Literal

from arclith.domain.ports.outbound.llm import LLMPort
from pydantic import BaseModel, Field


class IngredientIntent(BaseModel):
    action: Literal["create", "list"] = Field(
        description="Action métier à exécuter: create ou list.",
    )
    name: str | None = Field(
        default=None,
        description="Nom de l'ingrédient quand il est présent dans la demande.",
    )


class IngredientIntentPlanner:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def plan(self, prompt: str) -> IngredientIntent:
        return await self._llm.complete_structured(
            prompt,
            output_type=IngredientIntent,
            instructions=(
                "Tu traduis une demande utilisateur en commande JSON stricte pour un service pantry. "
                "Utilise action=create pour ajouter un ingrédient. "
                "Utilise action=list pour lister ou chercher des ingrédients. "
                "Ne choisis create que si un nom d'ingrédient explicite est présent."
            ),
        )
```

## 5. Brancher le nœud LangGraph sur le métier

Le fichier généré `src/pantry_agent/adapters/inbound/langgraph/agent.py` est volontairement minimal.
Pour ce quickstart, le remplacer par:

```python
from functools import lru_cache
from typing import Any, TypedDict

from arclith import Arclith
from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter
from langgraph.graph import END, START

from pantry_agent.application.planners.ingredient_intent import IngredientIntentPlanner
from pantry_agent.application.services.ingredient_service import IngredientService
from pantry_agent.domain.models.ingredient import Ingredient
from pantry_agent.infrastructure.containers.ingredient_container import build_ingredient_service


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    answer: str


arclith = Arclith("config")


@lru_cache(maxsize=1)
def _ingredient_service() -> IngredientService:
    service, _logger = build_ingredient_service(arclith)
    return service


@lru_cache(maxsize=1)
def _intent_planner() -> IngredientIntentPlanner:
    lm_settings = arclith.config.adapters.lm
    if lm_settings is None:
        raise RuntimeError("config/adapters/outbound/lm.yaml est requis pour le planner agent.")
    return IngredientIntentPlanner(PydanticAILLMAdapter(lm_settings))


def _last_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        role = message.get("role")
        if role in {"user", "human"}:
            return str(message.get("content", ""))
    return ""


async def run_agent(state: AgentState) -> AgentState:
    prompt = _last_user_message(state)
    service = _ingredient_service()
    if not prompt:
        answer = "Aucun message utilisateur reçu."
        messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
        return {**state, "messages": messages, "answer": answer}

    intent = await _intent_planner().plan(prompt)

    if intent.action == "create":
        if not intent.name:
            answer = "Je ne peux pas créer un ingrédient sans nom explicite."
        else:
            ingredient = await service.create(Ingredient(name=intent.name))
            answer = f"Ingrédient créé: {ingredient.name} ({ingredient.uuid})."
    else:
        ingredients, total = await service.find_page_filtered(name=intent.name, offset=0, limit=10)
        names = ", ".join(ingredient.name for ingredient in ingredients) or "aucun résultat"
        answer = f"Ingrédients trouvés ({total}): {names}."

    messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
    return {**state, "messages": messages, "answer": answer}


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="pantry_agent")
```

Pour une autre entité, remplacer `pantry_agent`, `Ingredient`, `build_ingredient_service` et les
prompts par les noms générés par `arclith-cli new`.

## 6. Lancer LangGraph Studio

Dans un terminal dedie:

```bash
uv run --frozen langgraph dev --no-browser --allow-blocking --port 2024
```

Dans LangGraph Studio, appeler le graphe `pantry_agent` avec un état:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "ajoute Sucre roux"
    }
  ]
}
```

Puis tester une lecture:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "liste les ingredients"
    }
  ]
}
```

Les runs doivent apparaitre dans le projet LangSmith configure par `LANGSMITH_PROJECT`.

## 7. Persistance partagée entre API et agent

Avec `repository: memory`, l'API lancée par `main.py` et le serveur `langgraph dev` ont chacun leur
processus et donc leur stockage mémoire. C'est suffisant pour valider les chemins d'exécution.

Pour partager les mêmes données entre l'API et l'agent local, brancher un repository persistant:

```bash
arclith-cli add-adapter \
  --capability repository \
  --adapter mongodb \
  --entity Ingredient \
  --db-name pantry_agent \
  --yes
```

Ensuite configurer l'URI MongoDB via le resolver de secrets local ou la configuration cible, sans
commiter de credential.

## 8. Gates de validation

Avant commit:

```bash
uv run --frozen python -m json.tool langgraph.json
uv run --frozen python -m pytest
uv run --frozen ruff check .
uv run --frozen mypy src tests
```

Smoke manuel minimal:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:1234/v1/models
```

Le quickstart est valide seulement si:

- l'API crée et relit une ressource `Ingredient`;
- LangGraph compile et expose le graphe `pantry_agent`;
- le nœud agent appelle le service applicatif généré;
- le planner applicatif traduit la demande en `IngredientIntent`;
- LM Studio répond sur `/v1/models`;
- LangSmith reçoit les traces quand `LANGSMITH_TRACING=true`.

## 9. Règles à conserver en projet réel

- Garder le domaine et les use cases indépendants de FastAPI, LangGraph, LangSmith et LM Studio.
- Faire produire au LLM un objet structuré, puis laisser les use cases appliquer le métier.
- Garder un planner deterministic ou des tests sans LLM pour les gates CI.
- Garder `.env` et les credentials hors Git.
- Utiliser LangGraph Studio et LangSmith pour tester les conversations et inspecter les traces.
