# Capability Secrets

Résolution de secrets avant validation de la configuration Arclith.

## Adapters

| Adapter | Usage |
|---|---|
| `env` | Docker, CI/CD, Kubernetes |
| `yaml` | développement local gitignoré |
| `vault` | HashiCorp Vault KV v2 |
| `chain` | fallback ordonné entre resolvers |

## Commande

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter chain \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/my-service/mongodb \
  --yes
```

## Configuration

```yaml
# config/secrets.yaml
resolver: chain
chain:
  - env
  - vault
  - yaml
mappings:
  adapters.mongodb.uri: apps/my-service/mongodb
```

## Règle

Aucune valeur secrète réelle ne doit être commitée.

## Validation

```bash
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
```

## Suite

Lire [Baseline production](../production/baseline.md).
