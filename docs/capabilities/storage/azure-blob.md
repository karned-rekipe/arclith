# Azure Blob Storage

`azure-blob` stocke les objets dans un container Azure Blob Storage.

## Installer

```bash
uv add "arclith[azure-blob]"
```

## Configuration

```yaml
# config/adapters/outbound/storage.yaml
adapter: azure-blob
account_url: "https://<account>.blob.core.windows.net"
container_name: "arclith-files"
prefix: "uploads"
connection_string: null
account_key: null
sas_token: null
use_default_credential: true
multitenant: false
```

| Champ | Role |
|---|---|
| `account_url` | URL du service Blob |
| `container_name` | container cible |
| `prefix` | prefixe applique devant les blobs |
| `connection_string` | mode connection string |
| `account_key` | mode cle de compte |
| `sas_token` | mode SAS |
| `use_default_credential` | utilise `DefaultAzureCredential` |
| `multitenant` | autorise les coordonnees Azure dans `TenantContext` |

Choisir un seul mode de credentials parmi `connection_string`, `account_key`,
`sas_token` et `use_default_credential`. L'adapter rejette une configuration
ambigue.

## Secrets

Mapper les secrets Azure dans `config/secrets.yaml`:

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
  adapters.storage.account_key: AZURE_STORAGE_ACCOUNT_KEY
  adapters.storage.sas_token: AZURE_STORAGE_SAS_TOKEN
```

Conserver les champs correspondants a `null` dans `storage.yaml` quand ils sont
resolus par secret mapping.

## RBAC Minimal

Avec Microsoft Entra ID et `use_default_credential: true`, assigner un role de
donnees Blob au principal applicatif. Une base simple est
`Storage Blob Data Contributor` au scope du container. Microsoft documente ce
role pour lire, ecrire et supprimer des containers/blobs, et recommande de
borner le scope au plus proche du besoin. Voir
[Assign an Azure role for access to blob data](https://learn.microsoft.com/en-us/azure/storage/blobs/assign-azure-role-data-access).

Si la politique de securite exige moins large, creer un role custom limite aux
operations de donnees necessaires au port: upload, download, properties, exists
et delete.

## Azurite Local

```yaml
# docker-compose.azurite.yml
services:
  azurite:
    image: mcr.microsoft.com/azure-storage/azurite:latest
    command: azurite-blob --blobHost 0.0.0.0 --loose
    ports:
      - "10000:10000"
    volumes:
      - azurite-data:/data

volumes:
  azurite-data:
```

Config locale:

```yaml
# config/adapters/outbound/storage.yaml
adapter: azure-blob
account_url: "http://127.0.0.1:10000/devstoreaccount1"
container_name: "arclith-files"
prefix: "uploads"
connection_string: null
account_key: null
sas_token: null
use_default_credential: false
multitenant: false
```

Secret local:

```yaml
# config/secrets.yaml
resolver: env
mappings:
  adapters.storage.connection_string: AZURE_STORAGE_CONNECTION_STRING
```

Injecter la connection string Azurite via l'environnement, creer le container
`arclith-files`, puis lancer le smoke test du [quickstart](quickstart.md).

## Multitenant

En `multitenant: true`, le contexte tenant peut fournir `account_url`,
`container_name`, `prefix`, `connection_string`, `account_key`, `sas_token` et
`use_default_credential`. Les alias `blob_service_url`, `container`, `conn_str`,
`storage_account_key`, `default_credential` et `managed_identity` sont acceptes.

## Limites Connues

- Pas de creation automatique de container.
- Pas de generation de SAS ou d'URL signee.
- Pas de lifecycle policy.
- Pas de CDN Azure Front Door.
- Pas de listing blob dans le port initial.

## Validation

```bash
uv run python -c "from arclith import Arclith; Arclith('config').file_storage()"
uv run python scripts/storage_smoke.py
```

Attendre la propagation RBAC avant de diagnostiquer un `FileStoragePermissionDenied`.
