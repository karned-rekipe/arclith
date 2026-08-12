# Capability Probe

Serveur de probes `health`, `readiness`, `info` et `metrics`.

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

- `/health`
- `/ready`
- `/info`
- `/metrics`

## Validation

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
```

## Suite

Lire [Docker](../runtime-docker.md).
