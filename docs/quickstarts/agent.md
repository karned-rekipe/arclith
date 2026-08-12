# Quickstart Agent

Ajouter un agent LangGraph minimal à un service.

## Prérequis

- Python 3.13
- `uv`
- LM Studio si tu utilises un LLM local

## Étapes

Si tu n'as pas encore de projet :

```bash
uvx --from arclith-cli arclith-cli init todo-agent --dir .
cd todo-agent
uv sync
```

```bash
uv add "arclith[langgraph]"
uvx --from arclith-cli arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --yes
```

Pour un LLM local :

```bash
uvx --from arclith-cli arclith-cli add-adapter \
  --capability llm \
  --adapter lmstudio \
  --param model_name="<model-id-lm-studio>" \
  --yes
```

## Validation

```bash
uv run langgraph dev
```

## Résultat

LangGraph Studio détecte le graphe généré depuis `langgraph.json`.

Le graphe généré est volontairement minimal. Le projet remplace ensuite l'état, les nœuds et les
transitions pour appeler ses use cases.

## Média

!!! note "Média à produire"
    Capture : LangGraph Studio avec le graphe chargé.
    Vidéo : ajout agent, lancement Studio, premier run.

## Suite

Lire [agent/langgraph](../capabilities/agent.md), puis le [parcours Todo agent](../tutorials/todo-list/06-agent.md).
