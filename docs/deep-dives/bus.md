# Deep Dive Bus

Cette page explique comment utiliser le command bus sans déplacer le métier dans
RabbitMQ.

## Position

Le bus est un adapter de coordination. Il transporte une intention vers un
handler applicatif.

```text
publisher
  -> CommandEnvelope
  -> RabbitMQ
  -> consumer
  -> CommandDispatcher
  -> CommandHandler
  -> use case
```

Le message ne doit pas contenir une implémentation métier. Il décrit une
commande.

## Envelope

Une commande doit transporter au minimum:

| Champ | Rôle |
|---|---|
| `command_type` | nom stable de la commande |
| `payload` | données de la commande |
| `correlation_id` | suivi bout en bout |
| `traceparent` | propagation OpenTelemetry si disponible |

Le `command_type` doit être versionnable si le contrat peut changer.

## Publisher

```python
await bus.publish(
    "todo.create",
    {"title": "Documenter le bus"},
    correlation_id="todo-doc-1",
)
```

Le publisher doit rester proche de l'événement applicatif qui déclenche la
commande. Il ne doit pas connaître le handler consommateur.

## Consumer

```python
dispatcher = CommandDispatcher()
dispatcher.register("todo.create", CreateTodoCommandHandler(create_todo_use_case))

app.run_command_bus(dispatcher)
```

Le handler transforme l'envelope en commande métier, puis appelle le use case.

## Ack Et Retry

| Situation | Comportement attendu |
|---|---|
| dispatch réussi | `ack` |
| payload invalide | `nack(requeue=False)` |
| erreur temporaire | retry borné |
| erreur persistante | DLX |
| shutdown | ne pas perdre les messages en cours |

Éviter le requeue infini. Une DLX doit permettre d'inspecter les messages qui
échouent durablement.

## Idempotence

Un consumer peut recevoir une commande plusieurs fois. Le handler doit donc
supporter les retries:

- clé idempotente dans le payload ou les métadonnées;
- use case tolérant aux doublons;
- logs corrélés avec `correlation_id`;
- métrique d'échec exploitable.

## Observabilité

Suivre au minimum:

| Signal | Utilité |
|---|---|
| message publié | vérifier la sortie |
| message consommé | vérifier l'entrée worker |
| durée handler | repérer les blocages |
| nack | diagnostiquer les erreurs |
| DLX | traiter les messages bloqués |

## Validation Locale

```bash
docker run --rm -d --name arclith-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:4-management

uv run pytest
docker stop arclith-rabbitmq
```

Pour un test d'intégration manuel, publier une commande, vérifier que le handler
s'exécute, puis inspecter RabbitMQ Management sur `http://127.0.0.1:15672`.

## Erreurs Fréquentes

| Erreur | Correction |
|---|---|
| payload sans version | versionner le `command_type` ou le schéma |
| handler non idempotent | ajouter une clé de déduplication |
| retry infini | configurer DLX et alerte |
| secret dans le payload | passer par la capability `secrets` |
| queue trop permissive | régler `prefetch` et `concurrency` |

## Pages Liées

- [Capability Command Bus](../capabilities/command-bus.md)
- [Command Bus RabbitMQ](../command-bus.md)
- [Capability Observability](../capabilities/observability.md)

## Média

!!! note "Média à produire"
    Capture : RabbitMQ Management avec exchange, queue et DLX.
    Vidéo : publication d'une commande et traitement par worker.
