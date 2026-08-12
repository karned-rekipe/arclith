# Secrets Et Vault

Cette page définit le flux minimal pour sortir les secrets du dépôt Git.

## Objectif

Le code et la configuration versionnée doivent contenir des références, jamais
des valeurs secrètes réelles.

## Stack Cible

| Besoin | Choix |
|---|---|
| Injection conteneur | variables d'environnement |
| Source centrale | Vault KV v2 |
| Fallback local | fichier YAML gitignoré |
| Résolution | `secrets/chain` |

## Ajouter L'adapter

```bash
arclith-cli add-adapter \
  --capability secrets \
  --adapter chain \
  --param field_path=adapters.mongodb.uri \
  --param secret_key=apps/my-service/mongodb \
  --yes
```

## Configuration Minimale

```yaml
# config/secrets.yaml
resolver: chain
chain:
  - env
  - vault
  - yaml
mappings:
  adapters.mongodb.uri: apps/my-service/mongodb
  cache.redis_url: apps/my-service/redis
```

## Règles

- Aucun `.env` réel dans Git.
- Les secrets de build sont interdits dans l'image Docker finale.
- Vault doit être la source de vérité en production.
- Le fallback YAML sert au développement local, avec un fichier ignoré.
- Chaque secret doit avoir un propriétaire, une rotation et un usage identifié.

## Vérifier

```bash
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
git diff --check
```

## Suite

Lire [observabilité](observability.md), puis la capability [secrets/vault](../capabilities/secrets.md).
