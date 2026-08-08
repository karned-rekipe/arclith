# 6. Ajouter un agent

Objectif: créer un agent LangGraph qui comprend une demande en langage naturel, choisit l'action
todo à exécuter, collecte seulement les champs vraiment manquants, puis appelle les mêmes ports
inbound que l'API et le MCP.

![Capture interactive agent](assets/06-agent.svg)

## Responsabilités de l'agent

- classifier l'intention: créer une todo, lister les todos, annuler une création en cours ou répondre
  que la demande n'est pas prise en charge;
- transformer une conversation en `TodoDraft`;
- conserver `draft` et `pending_field` dans l'état LangGraph pendant la phase de questionnement;
- appeler `CreateTodoPort` ou `ListTodosPort`.

Il ne connaît pas la persistance. Il ne parle ni à MongoDB ni au repository directement.

```text
message utilisateur
  -> adapter LangGraph
  -> intent-interpreter / parsing local
  -> CreateTodoPort ou ListTodosPort
  -> use case applicatif
  -> Repository[Todo]
```

## Générer les briques agent

Installer les dépendances:

```bash
uv add "arclith[langgraph]"
```

Créer les intent-interpreters:

```bash
touch src/todo_list_service/application/intent_interpreters/__init__.py
arclith-cli add-intent-interpreter
arclith-cli add-intent-interpreter
```

Répondre:

```text
Interpréteur d'intention (ex : IngredientIntent, todo_intent)
  Nom de l'interpréteur: TodoAction

Interpréteur d'intention (ex : IngredientIntent, todo_intent)
  Nom de l'interpréteur: TodoConversation
```

Créer la configuration LangGraph:

```bash
arclith-cli add-adapter --capability agent
```

Répondre:

```text
① Type d'adapter
   1  langgraph

  Votre choix (numéro ou nom): 1
  Nom du graphe LangGraph (agent): todo_agent
  Confirmer la génération ? [y/n] (y): y
```

Configurer aussi LM Studio et LangSmith avec les sous-étapes ci-dessous.

## Sous-étapes

1. [Configurer LM Studio et LangSmith](06-agent-config.md)
2. [Écrire les intent-interpreters](06-agent-intent-interpreters.md)
3. [Définir l'état et le parsing local](06-agent-state-parsing.md)
4. [Détecter l'action et collecter le draft](06-agent-action-collection.md)
5. [Formatter, router et injecter les dépendances](06-agent-routing-dependencies.md)
6. [Écrire les noeuds et assembler le graphe](06-agent-nodes-graph.md)
7. [Tester l'agent](06-agent-tests-studio.md)

## Rôle des fichiers LangGraph

| Fichier | Rôle |
| --- | --- |
| `application/intent_interpreters/todo_action.py` | Classe l'action globale: créer, lister, annuler ou inconnu. |
| `application/intent_interpreters/todo_conversation.py` | Extrait les champs d'une todo dans un `TodoDraft`. |
| `adapters/inbound/langgraph/agent.py` | Assemble le graphe LangGraph, déclare les noeuds et expose l'objet `agent` utilisé par `langgraph.json`. |
| `adapters/inbound/langgraph/state.py` | Définit `AgentState`, lit le dernier message utilisateur, reconstruit un `TodoDraft` depuis l'état, fabrique les messages assistant. |
| `adapters/inbound/langgraph/dependencies.py` | Centralise l'instance `Arclith`, l'adapter LLM et les ports applicatifs, avec cache local par process. |
| `adapters/inbound/langgraph/nodes.py` | Contient les fonctions de noeuds: router l'intention, collecter les champs, créer, lister, annuler, répondre inconnu. |
| `adapters/inbound/langgraph/routing.py` | Contient les fonctions de conditional edges LangGraph. |
| `adapters/inbound/langgraph/intent.py` | Fait la détection locale haute confiance, puis laisse les cas ambigus au LLM. |
| `adapters/inbound/langgraph/collection.py` | Met à jour le draft, applique les défauts, détecte les champs manquants et génère la prochaine question. |
| `adapters/inbound/langgraph/parsing.py` | Normalise le français, détecte les dates relatives, les statuts, l'annulation et les titres simples. |
| `adapters/inbound/langgraph/formatters.py` | Transforme le résultat de `ListTodosUseCase` en réponse lisible pour l'utilisateur et en payload JSON. |

Étape suivante: [configurer LM Studio et LangSmith](06-agent-config.md).
