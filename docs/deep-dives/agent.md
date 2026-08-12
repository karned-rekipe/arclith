# Deep Dive Agent

Cette page explique comment construire un agent Arclith sans casser la frontière
métier.

## Position

Un agent est un adapter inbound. Il reçoit une intention utilisateur, maintient
un état, puis appelle les use cases.

```text
message utilisateur
  -> graphe LangGraph
  -> node d'interprétation
  -> node d'action
  -> use case Arclith
  -> réponse agent
```

Le LLM aide à interpréter. Il ne remplace pas les règles métier.

## État Du Graphe

L'état doit être typé et limité aux informations utiles au parcours.

```python
class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    intent: str
    draft: dict[str, Any]
    created_uuid: str
```

Éviter un état fourre-tout. Chaque champ doit avoir un producteur et un
consommateur identifiables.

## Nodes

Un node doit faire une action claire:

| Node | Rôle |
|---|---|
| interprétation | classifier ou extraire une intention |
| validation | vérifier que les champs requis existent |
| action | appeler un use case |
| réponse | formater le retour utilisateur |

Un node d'action ne doit pas construire de repository concret.

## LLM

Utiliser le LLM pour les zones incertaines:

- comprendre une demande libre;
- extraire des champs depuis une phrase;
- choisir un chemin de graphe;
- reformuler une réponse.

Éviter le LLM quand une règle déterministe suffit. Une date déjà structurée ou
un statut connu ne nécessite pas un appel modèle.

## Appel Des Use Cases

```python
async def create_todo(state: AgentState) -> AgentState:
    command = CreateTodoCommand(title=state["draft"]["title"])
    todo = await create_todo_use_case.execute(command)
    return {**state, "created_uuid": str(todo.uuid)}
```

Le use case reste la seule couche qui orchestre le métier. L'agent prépare une
commande, puis délègue.

## Observabilité

Activer LangSmith pour inspecter:

| Signal | Utilité |
|---|---|
| messages | comprendre l'entrée utilisateur |
| choix de route | valider le graphe |
| appels LLM | suivre coût et latence |
| erreurs node | diagnostiquer un blocage |
| sorties use case | vérifier l'action réelle |

## Validation

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Tester aussi les nodes sans serveur LangGraph quand c'est possible. Les tests
unitaires doivent pouvoir utiliser un fake LLM.

## Erreurs Fréquentes

| Erreur | Correction |
|---|---|
| prompt qui écrit en base | passer par un use case |
| état non typé | définir un `TypedDict` explicite |
| node trop large | découper interprétation, validation et action |
| test dépendant du réseau | injecter un fake LLM |
| trace absente | vérifier la config LangSmith et `.env` |

## Pages Liées

- [Capability Agent](../capabilities/agent.md)
- [Capability LLM](../capabilities/llm.md)
- [Capability Observability](../capabilities/observability.md)
- [Tutoriel Todo Agent](../tutorials/todo-list/06-agent.md)

## Média

!!! note "Média à produire"
    Capture : LangGraph Studio.
    Vidéo : run agent de bout en bout.
