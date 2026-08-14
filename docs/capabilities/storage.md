# Capability Storage

`storage` ajoute un port outbound pour stocker des fichiers et des blobs sans
coupler les use cases a un SDK cloud ou au filesystem local.

## Pourquoi Un Port Dedie

`Repository[T]` persiste des entites metier: identifiants, statut, proprietaire,
droits, index et metadonnees utiles aux requetes. `FileStoragePort` persiste un
flux binaire: PDF, image, export, piece jointe ou resultat volumineux.

Les deux responsabilites restent separees:

| Besoin | Primitive |
|---|---|
| rechercher, filtrer, auditer une entite | `Repository[T]` |
| ecrire, lire ou supprimer un flux binaire | `FileStoragePort` |
| conserver le nom original, le statut, le tenant, l'auteur | entite metier |
| connaitre taille, checksum, etag, content-type provider | metadata storage |

Cette separation garde le domaine testable et rend le backend de fichiers
interchangeable: `filesystem` en local, puis S3, Azure Blob ou GCS en production.

## Guide

| Page | Contenu |
|---|---|
| [Quickstart filesystem](storage/quickstart.md) | config locale, volume Docker et smoke test executable |
| [Architecture](storage/architecture.md) | flux use case -> port -> adapter et frontiere avec `Repository[T]` |
| [Configuration](storage/configuration.md) | YAML, secrets, export config et validation Pydantic |
| [Securite](storage/security.md) | path traversal, noms utilisateurs, content-type, taille et permissions |
| [Multitenant](storage/multitenant.md) | bucket/container/prefix par tenant et implications d'isolation |
| [Use case complet](storage/use-case.md) | upload, metadata metier, download et delete |
| [Filesystem](storage/filesystem.md) | adapter local et volumes Docker/Kubernetes |
| [AWS S3](storage/s3.md) | config, MinIO, credentials, IAM minimal et smoke |
| [Azure Blob](storage/azure-blob.md) | config, secrets, RBAC, Azurite et smoke |
| [Google Cloud Storage](storage/gcs.md) | config, ADC/secrets, IAM et smoke |

## Contrat Commun

Le domaine depend uniquement de `FileStoragePort`:

| Methode | Role |
|---|---|
| `put(key, content, content_type=None, metadata=None)` | stocke un flux async et retourne `StoredObject` |
| `get(key)` | retourne `StoredObjectStream` avec metadata et flux async |
| `stat(key)` | lit les metadata sans telecharger le contenu |
| `exists(key)` | teste l'existence d'un objet |
| `delete(key)` | supprime l'objet; les adapters cloud restent idempotents sur absent |

Les metadata exposees sont neutres: `key`, `content_type`, `size`, `checksum`,
`etag`, `last_modified` et `custom`.

## Adapters Disponibles

| Adapter | Extra | Usage |
|---|---|---|
| `filesystem` | aucun | dev local, tests, Docker volume |
| `s3` | `arclith[s3]` | AWS S3 ou endpoint compatible comme MinIO |
| `azure-blob` | `arclith[azure-blob]` | Azure Blob Storage |
| `gcs` | `arclith[gcs]` | Google Cloud Storage |

## Limites Hors Scope

Le port couvre les operations objet minimales. Les sujets suivants doivent etre
traites dans le service consommateur ou dans l'infrastructure:

- antivirus et analyse de contenu;
- quotas par utilisateur ou tenant;
- lifecycle policies, retention legale et archivage froid;
- CDN, cache HTTP et invalidation edge;
- URLs signees et delegation de download direct;
- listing, recherche et indexation des objets;
- multipart/resumable upload expose au client final.

## Validation

```bash
make docs
uv run python -c "from arclith.infrastructure.config import load_config_dir; load_config_dir('config')"
```

Pour un premier flux executable, suivre le
[quickstart filesystem](storage/quickstart.md).
