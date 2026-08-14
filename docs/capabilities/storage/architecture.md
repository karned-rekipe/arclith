# Architecture Storage

`FileStoragePort` est un port outbound de stockage binaire. Il ne remplace pas
les repositories et ne connait pas les entites metier.

## Flux Canonique

```text
handler HTTP/MCP/worker
  -> use case applicatif
  -> FileStoragePort
  -> adapter filesystem, s3, azure-blob ou gcs
  -> backend de fichiers

use case applicatif
  -> Repository[T]
  -> metadata metier, droits, statut, audit, index
```

La route FastAPI ou le tool MCP adapte le transport. La decision metier reste
dans le use case, qui recoit `FileStoragePort` et `Repository[T]` en dependances.

## Responsabilites

| Couche | Responsabilite |
|---|---|
| domaine | definir l'entite et les regles metier |
| application | orchestrer upload/download/delete |
| `FileStoragePort` | contrat binaire provider-neutral |
| adapter storage | parler au SDK ou au filesystem |
| repository | persister les metadata metier |

## Cles D'objet

Les cles sont relatives et POSIX. `normalize_storage_key()` rejette:

- chaine vide;
- espace autour de la cle;
- separateur Windows `\`;
- chemin absolu;
- segment vide, `.`, `..`;
- chemin qui termine par `/`.

Exemples valides:

```text
tenant-a/invoices/2026-08.pdf
uploads/avatar.png
exports/report.csv
```

Exemples invalides:

```text
/tmp/file.txt
../secret.txt
tenant-a//file.txt
tenant-a/
```

## Metadata

`StoredObjectMetadata` expose les champs communs:

| Champ | Source typique |
|---|---|
| `key` | cle logique demandee au port |
| `content_type` | argument `put()` ou metadata provider |
| `size` | filesystem stat, S3/GCS/Azure properties |
| `checksum` | sha256 local ou checksum provider |
| `etag` | etag provider ou checksum local |
| `last_modified` | horodatage provider ou filesystem |
| `custom` | metadata custom mappees chez le provider |

Les metadata metier restent ailleurs: nom original, statut de validation,
proprietaire, visibilite, lien vers une entite parent, politique de retention.

## Factory

`Arclith("config").file_storage()` lit `config.adapters.storage`, puis delegue a
`build_file_storage()`. Le registre par defaut sait construire `filesystem`,
`s3`, `azure-blob` et `gcs`.

Un service peut injecter directement un fake `FileStoragePort` en test unitaire,
ou fournir un `FileStorageRegistry` dedie pour un adapter specifique.

## Erreurs Communes

| Erreur | Sens |
|---|---|
| `FileStorageInvalidKey` | cle invalide ou tentative de traversal |
| `FileStorageNotFound` | objet absent sur `get()` ou `stat()` |
| `FileStorageConflict` | conflit backend, par exemple repertoire a la place d'un fichier |
| `FileStoragePermissionDenied` | credentials ou permissions insuffisantes |
| `FileStorageUnavailable` | backend indisponible, config incomplete ou dependance absente |

Les use cases attrapent ces erreurs metier, pas les exceptions `boto3`,
`azure-storage-blob` ou `google-cloud-storage`.
