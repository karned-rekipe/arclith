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

### Utilisation Locale

```python
from arclith import Arclith

app = Arclith("config")
storage = app.file_storage()

async def save_invoice(content: bytes) -> str:
    await storage.put(
        "invoices/2026-08.pdf",
        _single_chunk(content),
        content_type="application/pdf",
        metadata={"kind": "invoice"},
    )
    return "invoices/2026-08.pdf"

async def _single_chunk(content: bytes):
    yield content
```

Le chemin `root_path` est un détail d'infrastructure. Les use cases manipulent
uniquement des clés relatives comme `invoices/2026-08.pdf`.

### Metadata Filesystem

L'adapter filesystem stocke le contenu dans `root_path/prefix/<key>` et les
métadonnées dans un sidecar JSON sous `.arclith-storage-metadata/`.

Cette stratégie garde le contenu lisible comme des fichiers standards, tout en
préservant `content_type`, `checksum`, `etag` et `custom`. Le répertoire
`.arclith-storage-metadata/` est réservé: une clé utilisateur ne peut pas
commencer par ce préfixe.

### Docker Compose

```yaml
services:
  api:
    image: my-service:local
    command: ["api"]
    user: "1001:1001"
    volumes:
      - file-storage:/data/files

volumes:
  file-storage:
```

Pour un bind mount local:

```yaml
services:
  api:
    volumes:
      - ./var/files:/data/files
```

Le dossier hôte doit appartenir à l'UID/GID utilisé dans le conteneur, par
exemple `1001:1001` si l'image suit la baseline non-root.

### Kubernetes

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-service-files
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service-api
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
      containers:
        - name: api
          image: ghcr.io/karned-rekipe/my-service:0.1.0
          volumeMounts:
            - name: file-storage
              mountPath: /data/files
      volumes:
        - name: file-storage
          persistentVolumeClaim:
            claimName: my-service-files
```

Avec plusieurs réplicas, un filesystem local ou un volume `ReadWriteOnce` ne
garantit pas le partage entre pods. Utiliser un stockage partagé compatible ou
un provider objet pour les workloads multi-réplicas.

### Production

- Exécuter l'image avec un utilisateur non-root qui peut écrire dans le volume.
- Sauvegarder le volume comme une donnée applicative.
- Éviter les symlinks dans `root_path`: l'adapter refuse ceux qui sortent de la
  racine, mais la plateforme doit aussi contrôler les permissions.
- Ne pas exposer `root_path` dans les erreurs retournées aux clients.

## AWS S3

Installer l'extra uniquement dans les services qui utilisent S3:

```bash
uv add "arclith[s3]"
```

L'installation de base d'Arclith ne charge pas `boto3`.

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

`endpoint_url: null` utilise AWS S3. Une URL explicite permet de viser MinIO ou
un backend compatible S3. `force_path_style: true` est requis par beaucoup de
backends locaux.

### Credentials

L'adapter garde la chaîne standard du SDK AWS par défaut. Ne pas écrire de clés
dans `storage.yaml`.

Sources courantes:

- rôle IAM de la plateforme;
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`;
- `AWS_PROFILE`;
- `AWS_REGION` ou `AWS_DEFAULT_REGION` si `region_name` n'est pas configuré.

En multitenant, le resolver tenant peut fournir les paramètres `bucket_name`,
`prefix`, `endpoint_url`, `region_name`, `force_path_style`, `profile_name`,
`aws_access_key_id`, `aws_secret_access_key` et `aws_session_token` dans
`AdapterTenantCoords` pour l'adapter `s3`.

### MinIO Local

```yaml
services:
  minio:
    image: quay.io/minio/minio:latest
    command: ["server", "/data", "--console-address", ":9001"]
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data

  minio-init:
    image: quay.io/minio/mc:latest
    depends_on: [minio]
    entrypoint: >
      /bin/sh -c "
      until mc alias set local http://minio:9000 minioadmin minioadmin; do sleep 1; done &&
      mc mb -p local/arclith-files || true
      "

volumes:
  minio-data:
```

Configuration Arclith depuis un conteneur du même compose:

```yaml
# config/adapters/outbound/storage.yaml
adapter: s3
bucket_name: "arclith-files"
prefix: "uploads"
region_name: "eu-west-3"
endpoint_url: "http://minio:9000"
force_path_style: true
multitenant: false
```

Variables locales:

```bash
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_DEFAULT_REGION=eu-west-3
```

Depuis la machine hôte hors Docker, utiliser
`endpoint_url: "http://127.0.0.1:9000"`.

### Use Case

```python
from collections.abc import AsyncIterator

from arclith import FileStoragePort, StoredObjectStream


class InvoiceStorageUseCase:
    def __init__(self, storage: FileStoragePort) -> None:
        self._storage = storage

    async def upload_pdf(self, invoice_id: str, content: AsyncIterator[bytes]) -> str:
        key = f"invoices/{invoice_id}.pdf"
        await self._storage.put(
            key,
            content,
            content_type="application/pdf",
            metadata={"kind": "invoice"},
        )
        return key

    async def download(self, key: str) -> StoredObjectStream:
        return await self._storage.get(key)
```

Le use case dépend de `FileStoragePort`, jamais de `boto3`. La route FastAPI ou
le tool MCP injecte le use case, pas le SDK S3.

### IAM Minimal

Pour un préfixe `uploads/` dans le bucket `my-bucket`, donner les permissions
objet minimales:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::my-bucket/uploads/*"
    }
  ]
}
```

`HeadObject` est couvert par `s3:GetObject`. Ajouter `s3:ListBucket` uniquement
si un use case applicatif liste des objets; le port `FileStoragePort` actuel ne
liste pas.

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

Pour S3, deux modèles sont recommandés:

- bucket par tenant: isolation forte, IAM plus simple par bucket;
- préfixe par tenant: mutualise le bucket, mais exige des policies bornées sur
  `arn:aws:s3:::bucket/<tenant-prefix>/*`.

Si les credentials sont résolus par tenant, stocker les clés dans le resolver
tenant, pas dans Git. Les coordonnées S3 attendues dans `TenantContext` sont
celles de l'adapter `s3`: `bucket_name`, `prefix`, `endpoint_url`,
`region_name`, `force_path_style`, `profile_name`, `aws_access_key_id`,
`aws_secret_access_key`, `aws_session_token`.

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
