# Exposer un cas d'usage sur plusieurs transports

`arclith-cli expose-usecase` prépare un contrat de transport, un mapper et un
enregistrement typé à partir d'un port inbound existant. FastAPI, FastMCP,
LangGraph et RabbitMQ exécutent ainsi le même `execute`, sans enveloppe JSON
intermédiaire pour les appels locaux.

```bash
arclith-cli init todo-service
cd todo-service
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
# Définir les champs de CreateTodoCommand et implémenter le use case.
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201 --dry-run
arclith-cli expose-usecase create-todo --via fastapi --feature todos \
  --path /v1/todos --method POST --status-code 201
arclith-cli expose-usecase create-todo --via fastmcp --feature todos
arclith-cli add-adapter --capability agent --adapter langgraph --yes
arclith-cli expose-usecase create-todo --via langgraph --feature todos
arclith-cli add-adapter --capability command-bus --adapter rabbitmq --yes
arclith-cli expose-usecase create-todo --via rabbitmq --feature todos \
  --command-type todo.create.v1
```

Chaque adapter dispose de son arborescence complète dès son installation, dont
`contracts/`. Une exposition ajoute les fichiers nommés d'une opération dans les
emplacements déjà établis. Le contrat d'entrée est une copie du modèle Pydantic
applicatif au moment de la génération. Son mapper valide ensuite la Command ou
Query attendue par le port. Le résultat est typé et son presenter est explicitement
personnalisable pour versionner le contrat public.

## Composition explicite et typée

L'agrégateur `adapters/inbound/fastapi/bindings_generated.py` expose par exemple :

```python
def register(target: FastAPI, *, create_todo: CreateTodoPort) -> None:
    register_create_todo(target, create_todo)
```

Le composition root construit le use case puis appelle ce registre :

```python
from todo_service.adapters.inbound.fastapi.bindings_generated import register
from todo_service.application.use_cases.create_todo import CreateTodoUseCase

register(api, create_todo=CreateTodoUseCase(repository))
```

Cette dernière liaison est explicite : le CLI ne devine pas quel repository,
transaction, identité ou autre dépendance convient à une classe applicative.
Les autres transports reçoivent la même instance de use case. Les lectures
`Query` utilisent GET par défaut dans FastAPI. Les commandes utilisent POST.
Les opérations FastMCP sont des tools ; resources et prompts restent des
primitives MCP distinctes dans les dossiers déjà créés.

Pour LangGraph, composer le `BindingState` généré dans l'état du graphe avant
d'enregistrer le node. Ses clés sont préfixées par le use case pour éviter les
collisions. Le registre ajoute le node ; `graph.py` définit explicitement ses
edges et sa politique de reprise. La sortie reste typée. Une query ne peut pas
être exposée sur le bus RabbitMQ sans contrat RPC explicite.

## Propriété, collisions et recettes

- Les contrats, routes, tools et nodes sont des fichiers développeur créés une fois.
- `bindings_generated.py` et `.arclith/bindings/<transport>.json` sont détenus par le CLI.
- Une deuxième exposition ajoute un import et un paramètre typé à l'agrégateur.
- Rejouer une exposition identique préserve les modifications manuelles.
- Un même nom public, type de commande ou couple méthode/chemin ne peut appartenir à deux bindings.
- `--dry-run` affiche les créations, mises à jour et fichiers préservés sans écrire de recette.
- La recette existante enregistre `expose-usecase` et permet son replay.
- Un test de contrat généré détecte la dérive du modèle applicatif depuis sa copie initiale.

Le scan est AST et n'exécute aucun module projet. Il prend en charge un port
`execute(self, request: CommandOrQuery) -> Result`, synchrone ou asynchrone,
avec un modèle Pydantic local héritant directement de `BaseModel`. Un modèle
hérité, générique, décoré ou comportant des méthodes/validateurs nécessite un
mapper explicite ; la commande refuse ces cas avant toute écriture. Les imports
relatifs, annotations différées et constantes littérales de module sont pris en
charge. Les dépendances locales non résolues ne sont pas copiées silencieusement.
Les paramètres HTTP GET/DELETE doivent être scalaires ou des listes de scalaires ;
les objets imbriqués et les paramètres de chemin nécessitent une route explicite.

Les use cases synchrones conservent une fonction de transport synchrone pour
permettre l'exécution hors de la boucle événementielle par le framework. Le
handler RabbitMQ utilise `asyncio.to_thread` pour ce cas. Avant l'application du
plan, le CLI revalide les chemins et le contenu des fichiers existants : une
modification concurrente annule l'écriture, sans écraser le travail développeur.

Le runtime RabbitMQ conserve les enveloppes, ACK, retry et DLX. Le binding valide
le payload puis appelle le port typé ; il ne transmet pas les headers du broker
au métier. Les tests du CLI exécutent les bindings HTTP, MCP, RabbitMQ et un graphe
LangGraph avec interruption/reprise contre le même contrat applicatif.
