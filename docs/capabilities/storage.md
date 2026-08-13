# Capability Storage

Stockage de fichiers et blobs derrière un port `FileStoragePort`.

## Objectif

`storage` est une capability outbound distincte de `repository`.

- `repository` persiste les entités métier.
- `storage` persiste des contenus binaires: documents, exports, images, archives.

Le domaine dépend du port `FileStoragePort`; l'adapter concret reste dans
l'infrastructure et la configuration.

## Contrat Commun

Le port expose cinq opérations:

| Méthode | Rôle |
|---|---|
| `put(key, content, ...)` | écrire un flux de bytes |
| `get(key)` | lire les métadonnées et le flux |
| `delete(key)` | supprimer un objet |
| `exists(key)` | tester l'existence |
| `stat(key)` | lire les métadonnées sans télécharger le contenu |

Les modèles provider-neutral sont:

- `StoredObjectMetadata`: clé, type MIME, taille, checksum, ETag,
  date de modification et métadonnées custom;
- `StoredObject`: métadonnées retournées après écriture;
- `StoredObjectStream`: métadonnées plus flux async de bytes.

## Clés D'objets

Une clé de stockage est un chemin POSIX relatif. Elle ne doit jamais dépendre
d'un chemin absolu local ou d'une URL provider.

Exemples valides:

```text
tenant-a/invoices/2026-08.pdf
exports/monthly/report.parquet
avatars/user-123.png
```

Exemples refusés:

```text
/absolute/file.txt
../private/file.txt
folder/../file.txt
folder//file.txt
folder\file.txt
```

Utiliser `normalize_storage_key()` avant de joindre une clé avec un chemin local
ou un préfixe backend. Cette règle protège les adapters filesystem contre la
traversée de dossiers et garde les adapters cloud interchangeables.

## Erreurs Communes

Tous les adapters storage doivent traduire leurs erreurs provider vers ces
exceptions:

| Erreur | Usage |
|---|---|
| `FileStorageInvalidKey` | clé vide, absolue, non normalisée ou avec traversée |
| `FileStorageNotFound` | objet absent |
| `FileStorageConflict` | conflit d'écriture ou condition backend non satisfaite |
| `FileStorageUnavailable` | backend indisponible |
| `FileStoragePermissionDenied` | credentials ou policy refusés |

Chaque erreur peut porter `key` pour aider les logs, sans exposer de secret.

## Installer

```bash
arclith-cli add-adapter --capability storage --adapter filesystem --yes
arclith-cli add-adapter --capability storage --adapter s3 --yes
arclith-cli add-adapter --capability storage --adapter azure-blob --yes
arclith-cli add-adapter --capability storage --adapter gcs --yes
```

Cette capability génère uniquement `config/adapters/outbound/storage.yaml`.
Elle ne modifie pas `config/adapters/adapters.yaml`, car il n'y a pas de
sélecteur repository à activer.

## Filesystem

Adapter cible pour un dossier monté dans Docker via volume.

```yaml
# config/adapters/outbound/storage.yaml
adapter: filesystem
root_path: "/data/files"
prefix: ""
create_root: true
multitenant: false
```

Monter `/data/files` sur un volume persistant dans Docker ou Kubernetes.
`prefix` reste relatif à `root_path`.

## AWS S3

```yaml
# config/adapters/outbound/storage.yaml
adapter: s3
bucket_name: "my-bucket"
prefix: ""
region_name: "eu-west-3"
endpoint_url: null
force_path_style: false
multitenant: false
```

`endpoint_url` permet de viser un backend compatible S3 comme MinIO.
Les credentials AWS doivent venir de l'environnement, d'un secret manager ou de
la capability [secrets](secrets.md).

## Azure Blob

```yaml
# config/adapters/outbound/storage.yaml
adapter: azure-blob
account_url: "https://<account>.blob.core.windows.net"
container_name: "my-container"
prefix: ""
multitenant: false
```

Les credentials Azure ne doivent pas être versionnés dans ce fichier.

## Google Cloud Storage

```yaml
# config/adapters/outbound/storage.yaml
adapter: gcs
bucket_name: "my-bucket"
prefix: ""
project_id: null
multitenant: false
```

`project_id: null` laisse le SDK ou l'environnement résoudre le projet courant.

## Multitenant

En mode single-tenant, la configuration doit contenir la cible backend minimale:

| Adapter | Champs requis |
|---|---|
| `filesystem` | `root_path` |
| `s3` | `bucket_name` |
| `azure-blob` | `account_url`, `container_name` |
| `gcs` | `bucket_name` |

En mode `multitenant: true`, l'adapter peut résoudre bucket, container ou
racine filesystem depuis le contexte tenant. Le contrat reste le même pour les
use cases.

## Règles

- Les use cases parlent au port `FileStoragePort`, jamais au SDK cloud.
- Les clés sont toujours relatives, normalisées et sans traversée.
- Les streams restent async pour éviter de charger les gros fichiers en mémoire.
- Les secrets provider ne sont pas stockés dans `storage.yaml`.
- Les adapters concrets traduisent leurs erreurs vers les exceptions communes.

## Validation

```bash
uv run pytest
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
```

## Suite

Ajouter ensuite l'adapter concret voulu: filesystem, Azure Blob, Google Cloud
Storage ou AWS S3.
