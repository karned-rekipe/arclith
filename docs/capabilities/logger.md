# Capability Logger

Logger applicatif partagé par les use cases et les adapters.

## Objectif

Fournir un port de logging commun pour les use cases, adapters et runners, avec
des métadonnées exploitables par l'observabilité.

## Adapter

| Adapter | Usage |
|---|---|
| `console` | logs Loguru vers `stderr`, enrichis si OpenTelemetry est actif |

## Commande

```bash
arclith-cli add-adapter --capability logger --adapter console --yes
```

## Configuration

```yaml
# config/adapters/adapters.yaml
logger: console
```

## Utiliser

```python
logger = arclith.logger
logger.info("todo created", todo_uuid=str(todo.uuid))
```

## Règles

- Les use cases reçoivent un logger injecté.
- Ne pas utiliser `print()` pour les logs applicatifs.
- Ne jamais logger de token, mot de passe ou payload sensible.
- Ajouter `correlation_id`, `tenant_id` ou `trace_id` quand disponibles.
- Laisser Uvicorn passer par l'interception Arclith.

## Validation

```bash
uv run pytest
```

## Suite

Lire [observability](observability.md) pour corréler logs et traces.
