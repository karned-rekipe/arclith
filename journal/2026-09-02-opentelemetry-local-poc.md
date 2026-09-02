# Documentation du POC OpenTelemetry local

- Remplacement de l'ébauche Jaeger du tutoriel Todo par un scénario reproductible avec image
  Jaeger 2.20.0 épinglée, attente de disponibilité et ports OTLP/UI explicités.
- Alignement de la commande non interactive sur le catalogue CLI `observability/opentelemetry` et
  désactivation des métriques, Jaeger étant utilisé comme backend de traces dans ce POC.
- Ajout d'une requête métier, de vérifications par l'API Jaeger, du parcours UI, du nettoyage et des
  erreurs fréquentes sans modifier le code métier.
- Validation manuelle du flux FastAPI vers OTLP HTTP : réponse HTTP 200, flush réussi, service
  `todo-list-service` indexé et une trace `GET /v1/todos/` retrouvée.
