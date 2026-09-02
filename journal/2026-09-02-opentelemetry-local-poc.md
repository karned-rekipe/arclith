# Documentation du POC OpenTelemetry local

## Contexte

La section Jaeger du tutoriel Todo indiquait l'image et l'endpoint local, mais ne proposait pas de
parcours reproductible permettant de prouver qu'une requête FastAPI apparaît réellement dans le
backend de traces.

## Décisions

- épingler Jaeger 2.20.0 et expliciter les ports OTLP HTTP et UI ;
- borner l'attente de disponibilité et afficher les logs du container en cas d'échec ;
- aligner la commande non interactive sur le catalogue CLI `observability/opentelemetry` ;
- désactiver les métriques, Jaeger étant utilisé comme backend de traces dans ce POC ;
- vérifier le service et les traces via l'API Jaeger avant le parcours visuel dans l'UI.

## Impact

Le tutoriel couvre désormais le lancement, la requête métier, la vérification, le nettoyage et les
erreurs fréquentes. Aucun code métier, contrat d'API ni comportement par défaut du framework n'est
modifié.

## Validation

- `make docs` et `make precommit` réussis ;
- commande CLI exécutée dans un projet fraîchement généré, avec activation et YAML vérifiés ;
- smoke FastAPI vers OTLP HTTP : réponse 200, flush réussi, service `todo-list-service` indexé et
  trace `GET /v1/todos/` retrouvée dans Jaeger.
