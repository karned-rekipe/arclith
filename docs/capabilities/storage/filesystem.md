# Filesystem Storage

`filesystem` stocke les objets dans un dossier local. C'est l'adapter de
developpement, de test et de deploiement simple avec volume Docker.

## Installer

Aucune dependance optionnelle n'est necessaire.

## Configuration

```yaml
# config/adapters/outbound/storage.yaml
adapter: filesystem
root_path: "/data/files"
prefix: "uploads"
create_root: true
multitenant: false
```

| Champ | Role |
|---|---|
| `root_path` | dossier racine du stockage |
| `prefix` | sous-prefixe logique ajoute devant les objets |
| `create_root` | cree le dossier racine si absent |
| `multitenant` | conserve pour symetrie config; l'adapter filesystem utilise `root_path` |

Avec cette config, la cle logique `invoices/a.pdf` est ecrite sous
`/data/files/uploads/invoices/a.pdf`.

## Metadata Locales

L'adapter conserve les metadata custom dans un dossier technique sous la racine:
`.arclith-storage-metadata`. Ce dossier appartient a l'implementation et ne doit
pas etre lu par les use cases.

Les fichiers visibles dans `root_path` restent les objets eux-memes. La metadata
metier durable reste dans un `Repository[T]`.

## Docker

Utiliser un volume persistant sur `/data/files`:

```yaml
services:
  app:
    image: my-service:local
    volumes:
      - file-storage:/data/files

volumes:
  file-storage:
```

Pour debugger depuis l'hote:

```yaml
services:
  app:
    volumes:
      - ./var/files:/data/files
```

Le dossier monte doit etre accessible en lecture/ecriture par l'utilisateur du
conteneur.

## Kubernetes

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: file-storage
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-service:latest
          volumeMounts:
            - name: file-storage
              mountPath: /data/files
      volumes:
        - name: file-storage
          persistentVolumeClaim:
            claimName: file-storage
```

Adapter `accessModes`, `storageClassName` et strategie de backup aux contraintes
du cluster.

## Securite

- Ne pas reutiliser le nom utilisateur comme chemin.
- Monter uniquement le dossier necessaire, pas tout le filesystem hote.
- Appliquer des permissions Unix strictes au volume.
- Sauvegarder le volume si les fichiers sont critiques.
- Ne pas partager le meme root path entre environnements.

## Validation

```bash
uv run python -c "from arclith import Arclith; Arclith('config').file_storage()"
uv run python scripts/storage_smoke.py
```

Le smoke test complet est decrit dans le
[quickstart filesystem](quickstart.md).
