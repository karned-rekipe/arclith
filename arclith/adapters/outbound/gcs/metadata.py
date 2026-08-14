from collections.abc import Mapping
from datetime import datetime
from typing import Any

from arclith.domain.ports.outbound.file_storage import StoredObjectMetadata


def metadata_from_blob(key: str, blob: Any) -> StoredObjectMetadata:
    return StoredObjectMetadata(
        key=key,
        content_type=blob_string(blob, "content_type"),
        size=blob_int(blob, "size"),
        checksum=blob_checksum(blob),
        etag=clean_etag(blob_string(blob, "etag")),
        last_modified=blob_datetime(blob, "updated"),
        custom=blob_custom_metadata(blob),
    )


def blob_value(blob: Any, field: str) -> Any:
    return getattr(blob, field, None)


def blob_string(blob: Any, field: str) -> str | None:
    value = blob_value(blob, field)
    if isinstance(value, str):
        return value
    return None


def blob_int(blob: Any, field: str) -> int | None:
    value = blob_value(blob, field)
    if isinstance(value, int) and value >= 0:
        return value
    return None


def blob_datetime(blob: Any, field: str) -> datetime | None:
    value = blob_value(blob, field)
    if isinstance(value, datetime):
        return value
    return None


def blob_metadata(blob: Any) -> dict[str, str]:
    metadata = blob_value(blob, "metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): str(value) for key, value in metadata.items() if isinstance(key, str)
    }


def blob_custom_metadata(blob: Any) -> dict[str, str]:
    metadata = blob_metadata(blob)
    generation = blob_provider_string(blob, "generation")
    if generation is not None:
        metadata.setdefault("gcs_generation", generation)
    metageneration = blob_provider_string(blob, "metageneration")
    if metageneration is not None:
        metadata.setdefault("gcs_metageneration", metageneration)
    return metadata


def blob_checksum(blob: Any) -> str | None:
    crc32c = blob_string(blob, "crc32c")
    if crc32c is not None:
        return f"crc32c:{crc32c}"
    md5_hash = blob_string(blob, "md5_hash")
    if md5_hash is not None:
        return f"md5:{md5_hash}"
    return None


def blob_provider_string(blob: Any, field: str) -> str | None:
    value = blob_value(blob, field)
    if value is None:
        return None
    return str(value)


def clean_etag(etag: str | None) -> str | None:
    if etag is None:
        return None
    return etag.strip('"')
