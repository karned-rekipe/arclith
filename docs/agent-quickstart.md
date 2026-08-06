# Quickstart agent Arclith from scratch

Ce guide part de zero et aboutit a un service local qui expose:

- une entite metier `Ingredient`;
- une API FastAPI generee par `arclith-cli`;
- un agent LangGraph teste dans LangGraph Studio;
- des traces LangSmith;
- un LLM local LM Studio via endpoint OpenAI-compatible.

La regle d'architecture reste la meme du debut a la fin:

```text
Demande naturelle
  -> adapter inbound LangGraph
  -> planner LLM derriere configuration locale
  -> commande structuree
  -> service/use case metier
  -> repository de l'entite
```

Le LLM traduit l'intention. Il ne doit pas ecrire directement dans la persistence.

## 1. Prerequis

- Python 3.13
- `uv`
- `git`
- LM Studio avec le Local Server demarre sur `http://127.0.0.1:1234/v1`
- un modele charge dans LM Studio
- une cle LangSmith si le tracing doit remonter dans LangSmith

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

## 2. Creer l'entite et l'API

Le scaffold cree l'entite `Ingredient`, les ports, le service applicatif, l'API FastAPI, MCP et les
probes.

```bash
mkdir -p ~/Perso/projets/demo
cd ~/Perso/projets/demo

arclith-cli new Ingredient pantry-agent --port 8100
cd pantry-agent
uv sync
```

Le premier `uv sync` cree `uv.lock`. Ensuite, utiliser `uv run --frozen ...` pour verifier que
l'environnement reste conforme au lockfile.

Lancer le service:

```bash
MODE=all uv run --frozen python main.py
```

Verifier les probes et l'API:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:8100/docs
```

Creer une ressource par API structuree:

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

Generer l'entrypoint LangGraph:

```bash
arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --param graph_name=pantry_agent \
  --yes
```

Generer la configuration LangSmith:

```bash
export LANGSMITH_API_KEY="<cle-langsmith>"

arclith-cli add-adapter \
  --capability observability \
  --adapter langsmith \
  --param project=pantry-agent-dev \
  --param endpoint=https://api.smith.langchain.com \
  --param api_key="$LANGSMITH_API_KEY" \
  --yes
```

Resultat attendu:

```text
langgraph.json
config/adapters/inbound/langgraph.yaml
config/adapters/outbound/langsmith.yaml
src/pantry_agent/adapters/inbound/langgraph/agent.py
.env
```

`langgraph.json` pointe vers `.env`; le serveur LangGraph local charge donc les variables
`LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` et `LANGSMITH_API_KEY`.

## 4. Configurer LM Studio

Dans LM Studio:

1. charger un modele;
2. demarrer le Local Server;
3. relever l'identifiant exact du modele.

Verifier les modeles exposes:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Ajouter la configuration LLM Arclith:

```bash
mkdir -p config/adapters/outbound
cat > config/adapters/outbound/lm.yaml <<'YAML'
provider: openai
model_name: "remplacer-par-le-model-id-lm-studio"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
YAML
```

`provider: openai` designe ici le protocole OpenAI-compatible, pas forcement le fournisseur OpenAI.
Si LM Studio tourne sur la machine hote et que l'agent tourne en container, remplacer souvent
`127.0.0.1` par `host.docker.internal`.

## 5. Brancher le noeud LangGraph sur le metier

Le fichier genere `src/pantry_agent/adapters/inbound/langgraph/agent.py` est volontairement minimal.
Pour ce quickstart, le remplacer par:

```python
from functools import lru_cache
from typing import Any, Literal, TypedDict

from arclith import Arclith
from arclith.infrastructure.lm import build_pydantic_ai_model
from langgraph.graph import END, START
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from pantry_agent.application.services.ingredient_service import IngredientService
from pantry_agent.domain.models.ingredient import Ingredient
from pantry_agent.infrastructure.containers.ingredient_container import build_ingredient_service


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    answer: str


class IngredientIntent(BaseModel):
    action: Literal["create", "list"] = Field(
        description="Action metier a executer: create ou list.",
    )
    name: str | None = Field(
        default=None,
        description="Nom de l'ingredient quand il est present dans la demande.",
    )


arclith = Arclith("config")


@lru_cache(maxsize=1)
def _ingredient_service() -> IngredientService:
    service, _logger = build_ingredient_service(arclith)
    return service


def _last_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        role = message.get("role")
        if role in {"user", "human"}:
            return str(message.get("content", ""))
    return ""


async def _plan(prompt: str) -> IngredientIntent:
    lm_settings = arclith.config.adapters.lm
    if lm_settings is None:
        raise RuntimeError("config/adapters/outbound/lm.yaml est requis pour le planner agent.")

    planner = Agent(
        build_pydantic_ai_model(lm_settings),
        output_type=IngredientIntent,
        instructions=(
            "Tu traduis une demande utilisateur en commande JSON stricte pour un service pantry. "
            "Utilise action=create pour ajouter un ingredient. "
            "Utilise action=list pour lister ou chercher des ingredients. "
            "Ne choisis create que si un nom d'ingredient explicite est present."
        ),
    )
    result = await planner.run(prompt)
    return result.output


async def run_agent(state: AgentState) -> AgentState:
    prompt = _last_user_message(state)
    service = _ingredient_service()
    if not prompt:
        answer = "Aucun message utilisateur recu."
        messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
        return {**state, "messages": messages, "answer": answer}

    intent = await _plan(prompt)

    if intent.action == "create":
        if not intent.name:
            answer = "Je ne peux pas creer un ingredient sans nom explicite."
        else:
            ingredient = await service.create(Ingredient(name=intent.name))
            answer = f"Ingredient cree: {ingredient.name} ({ingredient.uuid})."
    else:
        ingredients, total = await service.find_page_filtered(name=intent.name, offset=0, limit=10)
        names = ", ".join(ingredient.name for ingredient in ingredients) or "aucun resultat"
        answer = f"Ingredients trouves ({total}): {names}."

    messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
    return {**state, "messages": messages, "answer": answer}


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="pantry_agent")
```

Pour une autre entite, remplacer `pantry_agent`, `Ingredient`, `build_ingredient_service` et les
prompts par les noms generes par `arclith-cli new`.

## 6. Lancer LangGraph Studio

Dans un terminal dedie:

```bash
uv run --frozen langgraph dev --no-browser --allow-blocking --port 2024
```

Dans LangGraph Studio, appeler le graphe `pantry_agent` avec un etat:

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

## 7. Persistence partagee entre API et agent

Avec `repository: memory`, l'API lancee par `main.py` et le serveur `langgraph dev` ont chacun leur
processus et donc leur stockage memoire. C'est suffisant pour valider les chemins d'execution.

Pour partager les memes donnees entre l'API et l'agent local, brancher un repository persistant:

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

- l'API cree et relit une ressource `Ingredient`;
- LangGraph compile et expose le graphe `pantry_agent`;
- le noeud agent appelle le service applicatif genere;
- LM Studio repond sur `/v1/models`;
- LangSmith recoit les traces quand `LANGSMITH_TRACING=true`.

## 9. Regles a conserver en projet reel

- Garder le domaine et les use cases independants de FastAPI, LangGraph, LangSmith et LM Studio.
- Faire produire au LLM un objet structure, puis laisser les use cases appliquer le metier.
- Garder un planner deterministic ou des tests sans LLM pour les gates CI.
- Garder `.env` et les credentials hors Git.
- Utiliser LangGraph Studio et LangSmith pour tester les conversations et inspecter les traces.
