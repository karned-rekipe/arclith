import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from arclith.domain.ports.outbound.file_storage import FileStorageError

DEFAULT_STORAGE_CHUNK_SIZE = 1024 * 1024
DEFAULT_SPOOL_MAX_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class SpooledUpload:
    body: Any
    size: int
    checksum: str

    def close(self) -> None:
        self.body.close()


async def run_sync(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(callable_, *args, **kwargs)


async def spool_content(
    content: AsyncIterator[bytes],
    *,
    max_size: int = DEFAULT_SPOOL_MAX_SIZE,
) -> SpooledUpload:
    digest = hashlib.sha256()
    size = 0
    buffer = tempfile.SpooledTemporaryFile(max_size=max_size)
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


async def read_sync_body(
    body: Any,
    *,
    key: str,
    error_from_provider: Callable[[Exception], FileStorageError],
    chunk_size: int = DEFAULT_STORAGE_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    try:
        while True:
            chunk = await run_sync(body.read, chunk_size)
            if not chunk:
                break
            yield chunk
    except Exception as e:
        raise error_from_provider(e) from e
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            await run_sync(close)
