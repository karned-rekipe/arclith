# Capability API

Transport HTTP REST exposé via FastAPI.

## Adapter

| Adapter | Usage |
|---|---|
| `fastapi` | application FastAPI créée par `Arclith.fastapi()` |

## Commande

```bash
arclith-cli add-adapter --capability api --adapter fastapi --yes
```

## Configuration

```yaml
# config/adapters/inbound/fastapi.yaml
host: 0.0.0.0
port: 8000
reload: true
```

## Règle

Les routes FastAPI traduisent HTTP vers des use cases. Elles ne contiennent pas de logique métier
lourde.

## Validation

```bash
MODE=api uv run python main.py
curl -fsS http://127.0.0.1:9000/health
```

## Suite

Lire [Deep Dive API](../deep-dives/api.md).
