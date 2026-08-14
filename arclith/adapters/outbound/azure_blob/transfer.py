import asyncio
import hashlib
import queue
import tempfile
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from arclith.adapters.outbound.azure_blob.errors import (
    raise_azure_blob_storage_error,
)
from arclith.domain.ports.outbound.file_storage import (
    FileStorageError,
    FileStorageUnavailable,
)

_SPOOL_MAX_SIZE = 8 * 1024 * 1024
_END_OF_STREAM = object()


@dataclass(frozen=True)
class _ChunkError:
    error: Exception


@dataclass(frozen=True)
class SpooledUpload:
    body: Any
    size: int
    checksum: str

    def close(self) -> None:
        self.body.close()


async def spool_content(content: AsyncIterator[bytes]) -> SpooledUpload:
    digest = hashlib.sha256()
    size = 0
    buffer = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_SIZE)
    try:
        async for chunk in content:
            if not chunk:
                continue
            digest.update(chunk)
            size += len(chunk)
            await run_sync(buffer.write, chunk)
        await run_sync(buffer.seek, 0)
        return SpooledUpload(
            body=buffer,
            size=size,
            checksum=f"sha256:{digest.hexdigest()}",
        )
    except Exception:
        buffer.close()
        raise


def has_readable_downloader(downloader: Any) -> bool:
    return callable(getattr(downloader, "chunks", None)) or callable(
        getattr(downloader, "readall", None)
    )


async def read_downloader(downloader: Any, key: str) -> AsyncIterator[bytes]:
    try:
        chunks = getattr(downloader, "chunks", None)
        if callable(chunks):
            async for chunk in _iter_chunks(chunks()):
                if chunk:
                    yield chunk
            return

        readall = getattr(downloader, "readall", None)
        if callable(readall):
            body = await run_sync(readall)
            if body:
                yield bytes(body)
            return

        raise FileStorageUnavailable(
            "azure blob storage response body is unavailable", key=key
        )
    except FileStorageError:
        raise
    except Exception as e:
        raise_azure_blob_storage_error(e, key=key)
    finally:
        close = getattr(downloader, "close", None)
        if callable(close):
            await run_sync(close)


async def _iter_chunks(iterator: Any) -> AsyncIterator[bytes]:
    chunk_queue: queue.Queue[Any] = queue.Queue()
    threading.Thread(
        target=_produce_chunks,
        args=(iterator, chunk_queue),
        daemon=True,
    ).start()

    while True:
        item = await run_sync(chunk_queue.get)
        if item is _END_OF_STREAM:
            break
        if isinstance(item, _ChunkError):
            raise item.error
        yield item


def _produce_chunks(iterator: Any, chunk_queue: queue.Queue[Any]) -> None:
    try:
        for chunk in iterator:
            chunk_queue.put(chunk)
    except Exception as e:
        chunk_queue.put(_ChunkError(e))
    finally:
        chunk_queue.put(_END_OF_STREAM)


async def run_sync(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(callable_, *args, **kwargs)
