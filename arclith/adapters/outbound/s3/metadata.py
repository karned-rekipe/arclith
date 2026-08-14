from collections.abc import Mapping
from datetime import datetime
from typing import Any

from arclith.domain.ports.outbound.file_storage import StoredObjectMetadata


def metadata_from_response(key: str, response: Any) -> StoredObjectMetadata:
    return StoredObjectMetadata(
        key=key,
        content_type=response_string(response, "ContentType"),
        size=response_int(response, "ContentLength"),
        checksum=response_checksum(response),
        etag=clean_etag(response_string(response, "ETag")),
        last_modified=response_datetime(response, "LastModified"),
        custom=response_metadata(response),
    )


def response_value(response: Any, field: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(field)
    return None


def response_string(response: Any, field: str) -> str | None:
    value = response_value(response, field)
    if isinstance(value, str):
        return value
    return None


def response_int(response: Any, field: str) -> int | None:
    value = response_value(response, field)
    if isinstance(value, int) and value >= 0:
        return value
    return None


def response_datetime(response: Any, field: str) -> datetime | None:
    value = response_value(response, field)
    if isinstance(value, datetime):
        return value
    return None


def response_metadata(response: Any) -> dict[str, str]:
    metadata = response_value(response, "Metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): str(value) for key, value in metadata.items() if isinstance(key, str)
    }


def response_checksum(response: Any) -> str | None:
    for field, algorithm in (
        ("ChecksumSHA256", "sha256"),
        ("ChecksumSHA1", "sha1"),
        ("ChecksumCRC64NVME", "crc64nvme"),
        ("ChecksumCRC32C", "crc32c"),
        ("ChecksumCRC32", "crc32"),
    ):
        value = response_string(response, field)
        if value is not None:
            return f"{algorithm}:{value}"
    return None


def clean_etag(etag: str | None) -> str | None:
    if etag is None:
        return None
    return etag.strip('"')
