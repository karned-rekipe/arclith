import base64
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from arclith.domain.ports.outbound.file_storage import StoredObjectMetadata


def metadata_from_properties(key: str, properties: Any) -> StoredObjectMetadata:
    return StoredObjectMetadata(
        key=key,
        content_type=content_setting_string(properties, "content_type")
        or properties_string(properties, "content_type"),
        size=properties_first_int(properties, ("size", "content_length")),
        checksum=properties_checksum(properties),
        etag=clean_etag(properties_string(properties, "etag")),
        last_modified=properties_datetime(properties, "last_modified"),
        custom=properties_custom_metadata(properties),
    )


def properties_value(properties: Any, field: str) -> Any:
    if isinstance(properties, Mapping):
        return properties.get(field)
    return getattr(properties, field, None)


def properties_string(properties: Any, field: str) -> str | None:
    value = properties_value(properties, field)
    if isinstance(value, str):
        return value
    return None


def properties_first_int(properties: Any, fields: tuple[str, ...]) -> int | None:
    for field in fields:
        value = properties_value(properties, field)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def properties_datetime(properties: Any, field: str) -> datetime | None:
    value = properties_value(properties, field)
    if isinstance(value, datetime):
        return value
    return None


def content_setting_value(properties: Any, field: str) -> Any:
    settings = properties_value(properties, "content_settings")
    if settings is None:
        return None
    if isinstance(settings, Mapping):
        return settings.get(field)
    return getattr(settings, field, None)


def content_setting_string(properties: Any, field: str) -> str | None:
    value = content_setting_value(properties, field)
    if isinstance(value, str):
        return value
    return None


def properties_metadata(properties: Any) -> dict[str, str]:
    metadata = properties_value(properties, "metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): str(value) for key, value in metadata.items() if isinstance(key, str)
    }


def properties_custom_metadata(properties: Any) -> dict[str, str]:
    metadata = properties_metadata(properties)
    blob_type = provider_string(properties, "blob_type")
    if blob_type is not None:
        metadata.setdefault("azure_blob_type", blob_type)
    version_id = provider_string(properties, "version_id")
    if version_id is not None:
        metadata.setdefault("azure_version_id", version_id)
    return metadata


def properties_checksum(properties: Any) -> str | None:
    content_md5 = content_setting_value(properties, "content_md5")
    if content_md5 is None:
        content_md5 = properties_value(properties, "content_md5")
    if isinstance(content_md5, bytes):
        encoded = base64.b64encode(content_md5).decode("ascii")
        return f"md5:{encoded}"
    if isinstance(content_md5, str):
        return f"md5:{content_md5}"
    return None


def provider_string(properties: Any, field: str) -> str | None:
    value = properties_value(properties, field)
    if value is None:
        return None
    return str(value)


def clean_etag(etag: str | None) -> str | None:
    if etag is None:
        return None
    return etag.strip('"')
