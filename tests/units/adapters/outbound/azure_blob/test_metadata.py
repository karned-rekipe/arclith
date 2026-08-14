from datetime import UTC, datetime

from arclith.adapters.outbound.azure_blob.metadata import (
    clean_etag,
    metadata_from_properties,
)


def test_metadata_from_properties_maps_provider_fields() -> None:
    content_settings = type(
        "ContentSettings",
        (),
        {"content_type": "text/plain", "content_md5": b"provider-md5"},
    )()
    properties = type(
        "BlobProperties",
        (),
        {
            "content_settings": content_settings,
            "size": 11,
            "etag": '"etag"',
            "last_modified": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            "metadata": {"owner": "tenant-a"},
            "blob_type": "BlockBlob",
            "version_id": "version-a",
        },
    )()

    metadata = metadata_from_properties("docs/readme.txt", properties)

    assert metadata.key == "docs/readme.txt"
    assert metadata.content_type == "text/plain"
    assert metadata.size == 11
    assert metadata.checksum == "md5:cHJvdmlkZXItbWQ1"
    assert metadata.etag == "etag"
    assert metadata.custom == {
        "owner": "tenant-a",
        "azure_blob_type": "BlockBlob",
        "azure_version_id": "version-a",
    }


def test_metadata_from_properties_accepts_mapping_payload() -> None:
    metadata = metadata_from_properties(
        "docs/readme.txt",
        {
            "content_type": "text/plain",
            "content_length": 11,
            "content_md5": "provider-md5",
            "etag": '"etag"',
            "metadata": {"owner": "tenant-a"},
        },
    )

    assert metadata.content_type == "text/plain"
    assert metadata.size == 11
    assert metadata.checksum == "md5:provider-md5"
    assert metadata.etag == "etag"
    assert metadata.custom == {"owner": "tenant-a"}


def test_clean_etag_handles_missing_value() -> None:
    assert clean_etag(None) is None
