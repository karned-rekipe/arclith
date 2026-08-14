# Google Cloud Storage

`gcs` stocke les objets dans Google Cloud Storage.

## Installer

```bash
uv add "arclith[gcs]"
```

## Configuration

```yaml
# config/adapters/outbound/storage.yaml
adapter: gcs
bucket_name: "arclith-files"
prefix: "uploads"
project_id: "my-project"
credentials_path: null
credentials_json: null
credentials_json_b64: null
multitenant: false
```

| Champ | Role |
|---|---|
| `bucket_name` | bucket cible |
| `prefix` | prefixe applique devant les objets |
| `project_id` | projet GCP passe au client |
| `credentials_path` | chemin vers un service account JSON monte |
| `credentials_json` | service account JSON injecte par secret |
| `credentials_json_b64` | service account JSON encode en base64 |
| `multitenant` | autorise les coordonnees GCS dans `TenantContext` |

Si aucun credential explicite n'est fourni, le SDK utilise les Application
Default Credentials du runtime.

## ADC Et Secrets

Preferer ADC sur Cloud Run, GKE ou Compute Engine. Pour un service account JSON
local ou CI, ne jamais commiter le JSON. Mapper plutot le champ Arclith:

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
  adapters.storage.credentials_json_b64: GCS_SERVICE_ACCOUNT_JSON_B64
```

`credentials_path` doit pointer vers un fichier monte par le runtime. Le chemin
peut etre versionne; le contenu du fichier ne doit pas l'etre.

## IAM Minimal

Une base simple au niveau bucket est `roles/storage.objectUser`, qui donne acces
a la creation, lecture, mise a jour et suppression d'objets. Google documente
aussi les permissions fines comme `storage.objects.create`,
`storage.objects.get`, `storage.objects.update` et `storage.objects.delete`.
Voir
[IAM roles for Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/iam-roles).

Pour un perimetre plus strict, creer un role custom limite aux operations du
port. `FileStoragePort` ne liste pas les objets; ne pas ajouter
`storage.objects.list` sauf si un use case de listing est introduit.

## Smoke Test

Google ne fournit pas d'emulateur GCS officiel equivalent a Azurite ou MinIO
pour ce flux. Utiliser un bucket sandbox reel et un prefixe dedie:

```yaml
# config/adapters/outbound/storage.yaml
adapter: gcs
bucket_name: "arclith-storage-sandbox"
prefix: "smoke"
project_id: "my-project"
credentials_path: null
credentials_json: null
credentials_json_b64: null
multitenant: false
```

Lancer ensuite le smoke test du [quickstart](quickstart.md). Le script ecrit,
lit, verifie `exists`, supprime puis reverifie `exists`.

## Multitenant

En `multitenant: true`, le contexte tenant peut fournir `bucket_name`, `prefix`,
`project_id`, `credentials_path`, `credentials_json` et `credentials_json_b64`.
Les alias `project`, `service_account_file`, `service_account_json` et
`service_account_json_b64` sont acceptes.

## Limites Connues

- Pas de creation automatique de bucket.
- Pas de signed URL.
- Pas de lifecycle policy.
- Pas de CDN Cloud CDN.
- Pas de listing objet dans le port initial.
- Pas de resumable upload expose au client final.

## Validation

```bash
uv run python -c "from arclith import Arclith; Arclith('config').file_storage()"
uv run python scripts/storage_smoke.py
```

Ne jamais utiliser un bucket de production pour le smoke test.
