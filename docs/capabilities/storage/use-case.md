# Use Case Complet

Cet exemple montre la frontière attendue : le use case manipule le port storage
et le repository métier. Il ne dépend d'aucun SDK provider.

## Entite De Metadata

```python
from uuid import UUID

from arclith import Entity


class Document(Entity):
    owner_id: UUID
    storage_key: str
    original_filename: str
    content_type: str | None
    size: int | None
    checksum: str | None
```

Le nom original, le proprietaire et les droits restent dans l'entite. Le backend
storage ne sert pas de catalogue metier.

## Upload

```python
from collections.abc import AsyncIterator
from uuid import UUID

from uuid6 import uuid7

from arclith import FileStoragePort, Repository


class UploadDocument:
    def __init__(
        self,
        storage: FileStoragePort,
        repository: Repository[Document],
    ) -> None:
        self._storage = storage
        self._repository = repository

    async def execute(
        self,
        *,
        owner_id: UUID,
        original_filename: str,
        content: AsyncIterator[bytes],
        content_type: str | None,
    ) -> Document:
        extension = original_filename.rsplit(".", maxsplit=1)[-1].lower()
        key = f"{owner_id}/documents/{uuid7()}.{extension}"

        stored = await self._storage.put(
            key,
            content,
            content_type=content_type,
            metadata={"owner_id": str(owner_id)},
        )

        document = Document(
            owner_id=owner_id,
            storage_key=stored.key,
            original_filename=original_filename,
            content_type=stored.content_type,
            size=stored.size,
            checksum=stored.checksum,
        )
        return await self._repository.create(document)
```

## Download

```python
from uuid import UUID

from arclith import FileStoragePort, Repository, StoredObjectStream


class DownloadDocument:
    def __init__(
        self,
        storage: FileStoragePort,
        repository: Repository[Document],
    ) -> None:
        self._storage = storage
        self._repository = repository

    async def execute(self, document_id: UUID) -> tuple[Document, StoredObjectStream]:
        document = await self._repository.read(document_id)
        if document is None:
            raise LookupError("document metadata not found")

        stream = await self._storage.get(document.storage_key)
        return document, stream
```

Le handler HTTP transforme ensuite `stream.body` en reponse streaming. Cette
conversion appartient au transport, pas au use case.

## Delete

```python
from uuid import UUID

from arclith import FileStoragePort, Repository


class DeleteDocument:
    def __init__(
        self,
        storage: FileStoragePort,
        repository: Repository[Document],
    ) -> None:
        self._storage = storage
        self._repository = repository

    async def execute(self, document_id: UUID) -> None:
        document = await self._repository.read(document_id)
        if document is None:
            return

        await self._storage.delete(document.storage_key)
        await self._repository.delete(document_id)
```

Selon le produit, l'ordre peut etre inverse ou compense par une file de retry.
Le point important est de garder le choix transactionnel dans l'application, pas
dans l'adapter.

## Tests Unitaires

Injecter un fake `FileStoragePort` suffit pour tester les regles du use case. Les
smoke tests provider restent separes et verifies avec les pages
[Filesystem](filesystem.md), [S3](s3.md), [Azure Blob](azure-blob.md) ou
[GCS](gcs.md).
