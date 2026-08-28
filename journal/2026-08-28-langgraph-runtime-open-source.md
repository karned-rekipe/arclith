# Runtime LangGraph Durable Open Source

## Contexte

Les agents Arclith utilisaient `langgraph dev`, dont les threads et checkpoints disparaissent au
redémarrage. Le serveur standalone officiel de production n'est pas utilisable sans clé de licence
LangGraph Cloud.

## Changements

- ajout d'un serveur FastAPI autonome compatible avec les routes threads/runs utilisées par Jarvis ;
- persistance des checkpoints et du store via les adapters PostgreSQL officiels de LangGraph ;
- catalogue PostgreSQL des threads et runs ;
- coordination Redis des verrous par thread et demandes d'annulation ;
- streaming SSE `metadata`, `values`, `custom` et `messages` ;
- reprise par checkpoint/command, historique, état et suppression ;
- sélection par `ARCLITH_AGENT_RUNTIME=durable` dans l'entrypoint Docker généré ;
- extra optionnel `arclith[langgraph-runtime]` et commande `arclith-agent-runtime` ;
- documentation du contrat, des limites et des garde-fous Kubernetes.

## Sécurité et exploitation

Les URI restent exclusivement dans l'environnement runtime. Les erreurs SSE sont assainies. Le
runtime expose `/ready`, borne son pool PostgreSQL, impose un seul run par thread et applique un
timeout. PostgreSQL est la source durable ; Redis ne contient que des données de coordination à TTL.

## Validation

- tests unitaires du contrat HTTP/SSE, reprise, concurrence, annulation, catalogue et cycle de vie ;
- lint Ruff, mypy, Bandit et seuil Radon ;
- couverture projet supérieure ou égale à 90 % ;
- build strict de la documentation.
