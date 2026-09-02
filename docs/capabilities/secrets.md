# Capability Secrets

Résolution de secrets avant validation de la configuration Arclith.

## Objectif

Remplacer les valeurs sensibles dans la configuration par des références
résolues au runtime.

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

## Configuration Générée

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

## Resolvers

| Resolver | À Utiliser Quand |
|---|---|
| `env` | Docker, CI/CD, Kubernetes |
| `yaml` | POC local avec fichier gitignoré |
| `vault` | production |
| `chain` | fallback ordonné `env`, `vault`, `yaml` |

## Mappings

```yaml
mappings:
  adapters.mongodb.uri: apps/my-service/mongodb
  adapters.mariadb.password: apps/my-service/mariadb/password
  cache.redis_url: apps/my-service/redis
```

La clé de gauche est le champ Arclith. La valeur de droite est la référence dans
le resolver choisi.

## Règles

- Aucune valeur secrète réelle ne doit être commitée.
- Ne pas injecter de secret au build Docker.
- Préférer Vault comme source de vérité en production.
- Garder les fichiers YAML locaux gitignorés.
- Documenter propriétaire, rotation et usage de chaque secret.

## Validation

```bash
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
git diff --check
```

Le [POC Vault du tutoriel Todo](../tutorials/todo-list/07-local-services.md#ajouter-vault-localement)
montre le lancement du serveur dev, le seed KV v2 et la résolution d'un secret applicatif sans
afficher sa valeur.

## Suite

Lire [Secrets et Vault](../production/secrets.md), puis [tenant](tenant.md).
