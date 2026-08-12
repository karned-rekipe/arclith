# Capability Probe

Serveur de probes `health`, `readiness`, `info` et `metrics`.

## Objectif

Exposer un canal opérationnel indépendant du transport métier pour vérifier la
santé, la readiness, les transports actifs et les métriques.

## Adapter

| Adapter | Usage |
|---|---|
| `server` | serveur HTTP transverse de probes |

## Commande

```bash
arclith-cli add-adapter --capability probe --adapter server --yes
```

## Configuration

```yaml
# config/adapters/inbound/probe.yaml
host: 0.0.0.0
port: 9000
enabled: true
```

## Endpoints

| Endpoint | Usage |
|---|---|
| `/health` | le processus répond |
| `/ready` | le service est prêt à recevoir du trafic |
| `/info` | nom, version et transports actifs |
| `/metrics` | métriques API/MCP quand activées |

## Readiness

```python
async def database_ready() -> bool:
    return await repository.ping()

arclith.add_readiness_check(database_ready)
```

## Règles

- Utiliser un port de probe séparé du port métier.
- Kubernetes doit router la readiness vers `/ready`.
- Une dépendance critique indisponible doit rendre `/ready` négatif.
- `/health` ne remplace pas `/ready`.
- Les probes ne doivent pas exposer de secret.

## Validation

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
```

## Suite

Lire [Runtime et probes](../production/runtime.md), puis [Docker](../runtime-docker.md).
