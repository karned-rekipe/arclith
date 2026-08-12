# Capability Logger

Logger applicatif partagé par les use cases et les adapters.

## Adapter

| Adapter | Usage |
|---|---|
| `console` | logs Loguru vers `stderr` |

## Commande

```bash
arclith-cli add-adapter --capability logger --adapter console --yes
```

## Configuration

```yaml
# config/adapters/adapters.yaml
logger: console
```

## Règle

Les use cases reçoivent un logger injecté. Ils n'utilisent pas `print()`.

## Validation

```bash
uv run pytest
```

## Suite

Lire [observability](observability.md) pour corréler logs et traces.
