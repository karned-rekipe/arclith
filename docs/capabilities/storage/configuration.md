# Configuration Storage

La configuration storage est portee par `StorageSettings` et chargee depuis
`config/adapters/outbound/storage.yaml`.

## Fichier Scoped

```yaml
# config/adapters/outbound/storage.yaml
adapter: filesystem
root_path: "/data/files"
prefix: "uploads"
create_root: true
multitenant: false
```

Dans un dossier `config/`, ce fichier est merge sous `adapters.storage`.

## Champs Communs

| Champ | Type | Description |
|---|---|---|
| `adapter` | `filesystem`, `s3`, `azure-blob`, `gcs` | backend selectionne |
| `prefix` | string | prefixe applique devant chaque cle objet |
| `multitenant` | bool | autorise la resolution de cible via `TenantContext` |

`prefix` utilise la meme validation que les cles objet. Il doit rester relatif,
normalise et sans segment `..`.

## Champs Par Adapter

| Adapter | Champs requis en single-tenant | Champs optionnels |
|---|---|---|
| `filesystem` | `root_path` | `prefix`, `create_root`, `multitenant` |
| `s3` | `bucket_name` | `prefix`, `region_name`, `endpoint_url`, `force_path_style`, `multitenant` |
| `azure-blob` | `account_url`, `container_name` | `prefix`, `connection_string`, `account_key`, `sas_token`, `use_default_credential`, `multitenant` |
| `gcs` | `bucket_name` | `prefix`, `project_id`, `credentials_path`, `credentials_json`, `credentials_json_b64`, `multitenant` |

En `multitenant: true`, la cible minimale peut venir du contexte tenant. La
config de base peut donc omettre bucket, container ou root path si le resolver
tenant les fournit a chaque requete.

## Secrets

Les secrets ne doivent pas etre mis directement dans `storage.yaml`. Utiliser
`config/secrets.yaml` pour mapper un champ Arclith vers un resolver `env`,
`yaml`, `vault` ou `chain`.

```yaml
# config/secrets.yaml
resolver: chain
chain:
  - env
  - vault
  - yaml
vault:
  addr: "http://vault:8200"
  mount: "kv"
yaml:
  path: "secrets.yaml"
mappings:
  adapters.storage.connection_string: AZURE_STORAGE_CONNECTION_STRING
  adapters.storage.credentials_json_b64: GCS_SERVICE_ACCOUNT_JSON_B64
```

La valeur de gauche est le champ Arclith a alimenter. La valeur de droite est la
reference lue par le resolver. Avec `env`, Arclith essaie la cle explicite puis
la cle derivee du champ.

S3 suit la chaine de credentials standard `boto3` en single-tenant. Les champs
AWS access key ne sont pas dans `StorageSettings`; utiliser un role IAM, un
profil AWS, les variables standard du SDK ou des credentials par tenant via
`TenantContext`.

## Export Config

Pour Kubernetes ou un runtime qui consomme un seul fichier YAML:

```bash
uv run python - <<'PY'
from pathlib import Path

from arclith import export_config_yaml

export_config_yaml(Path("config"), Path("dist/config.yaml"))
PY
```

`export_config_yaml()` merge la config versionnee et conserve les mappings de
secrets. Il n'ecrit pas les valeurs secretes resolues dans le fichier exporte.

## Validation

```bash
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
uv run python -c "from arclith.infrastructure.config import load_config_file; load_config_file('dist/config.yaml')"
```

La validation Pydantic echoue si un champ inconnu est present ou si la cible
requise du backend manque en single-tenant.
