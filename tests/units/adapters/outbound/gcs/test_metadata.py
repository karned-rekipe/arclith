from datetime import UTC, datetime

from arclith.adapters.outbound.gcs import metadata as gcs_metadata


def test_gcs_blob_helpers_tolerate_incomplete_provider_payloads() -> None:
    class EmptyBlob:
        pass

    class InvalidBlob:
        content_type = 42
        size = -1
        etag = None
        updated = "not-a-date"
        metadata = "not-a-mapping"

    empty_metadata = gcs_metadata.metadata_from_blob("docs/readme.txt", EmptyBlob())
    invalid_metadata = gcs_metadata.metadata_from_blob("docs/readme.txt", InvalidBlob())

    assert empty_metadata.content_type is None
    assert empty_metadata.size is None
    assert empty_metadata.etag is None
    assert empty_metadata.custom == {}
    assert invalid_metadata.content_type is None
    assert invalid_metadata.size is None
    assert invalid_metadata.last_modified is None
    assert invalid_metadata.custom == {}
    assert gcs_metadata.blob_checksum(EmptyBlob()) is None
    assert gcs_metadata.clean_etag(None) is None


def test_gcs_blob_helpers_preserve_provider_metadata() -> None:
    class Blob:
        content_type = "text/plain"
        size = 12
        etag = '"etag"'
        updated = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        metadata = {"owner": "tenant-a"}
        crc32c = "crc32c-value"
        generation = 123
        metageneration = "2"

    metadata = gcs_metadata.metadata_from_blob("docs/readme.txt", Blob())

    assert metadata.content_type == "text/plain"
    assert metadata.size == 12
    assert metadata.etag == "etag"
    assert metadata.checksum == "crc32c:crc32c-value"
    assert metadata.custom == {
        "owner": "tenant-a",
        "gcs_generation": "123",
        "gcs_metageneration": "2",
    }
