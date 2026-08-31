# Revue structurelle et lisibilité du code

## Contexte

Une revue transverse du framework et de son CLI a mis en évidence quelques modules devenus trop
volumineux et plusieurs responsabilités techniques regroupées dans une même façade. Les définitions
répétées observées sur `repository()` ont également été auditées : il s'agit de surcharges de typage
valides, suivies d'une seule implémentation runtime, et non d'un écrasement accidentel.

## Décisions

- conserver les surcharges `repository()` qui garantissent le type de retour des registres
  personnalisés, tout en maintenant une seule implémentation exécutable ;
- garder `AppConfig`, `Arclith`, le catalogue de capabilities et la commande `add-adapter` comme
  façades publiques stables, puis déplacer leurs responsabilités cohérentes dans des modules dédiés ;
- isoler les cycles de vie OpenTelemetry, les intégrations LangSmith et les catalogues du runtime
  LangGraph sans introduire de dépendance obligatoire entre extras optionnels ;
- privilégier la composition pour les bootstraps FastAPI, FastMCP et LangGraph afin que la façade
  `Arclith` reste lisible et que chaque composant ait une responsabilité explicite ;
- éviter une abstraction commune artificielle entre adapters lorsque leurs contrats de ressources,
  de concurrence ou de persistance diffèrent réellement ;
- ajouter un test de structure qui détecte les définitions non intentionnellement dupliquées et les
  champs répétés dans une même portée, les instructions AST adjacentes identiques et les modules de
  production supérieurs à 600 lignes ; le motif standard `@overload` suivi d'une implémentation reste
  explicitement autorisé ;
- marquer chaque dossier source Python comme package explicite : sans `__init__.py`, Hatch incluait
  les fichiers dans la wheel mais `zipimport` ne pouvait pas résoudre plusieurs adapters.

## Compatibilité

Les imports historiques depuis `arclith.infrastructure.config`,
`arclith.adapters.inbound.langgraph_runtime.catalog` et `arclith_cli.capabilities` restent disponibles.
Les signatures publiques, la configuration YAML, les extras optionnels et les comportements runtime
ne changent pas. Les nouveaux modules sont des limites internes de responsabilité.

## Validation

- tests ciblés après chaque extraction de module ;
- analyse Ruff, mypy, Bandit et Radon ;
- suite complète du framework et du CLI ;
- couverture globale supérieure ou égale à 90 % ;
- construction stricte de la documentation ;
- construction des wheels framework/CLI et imports directs depuis les archives ;
- vérification Git des erreurs d'espacement et revue du diff final.
