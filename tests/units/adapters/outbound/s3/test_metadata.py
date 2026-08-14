from arclith.adapters.outbound.s3 import metadata as s3_metadata


def test_s3_response_helpers_tolerate_incomplete_provider_payloads() -> None:
    empty_metadata = s3_metadata.metadata_from_response("docs/readme.txt", object())
    invalid_metadata = s3_metadata.metadata_from_response(
        "docs/readme.txt",
        {
            "ContentType": 42,
            "ContentLength": -1,
            "ETag": None,
            "LastModified": "not-a-date",
            "Metadata": "not-a-mapping",
        },
    )

    assert empty_metadata.content_type is None
    assert empty_metadata.size is None
    assert empty_metadata.etag is None
    assert empty_metadata.custom == {}
    assert invalid_metadata.content_type is None
    assert invalid_metadata.size is None
    assert invalid_metadata.last_modified is None
    assert invalid_metadata.custom == {}
    assert (
        s3_metadata.response_checksum({"ChecksumCRC32": "crc32-value"})
        == "crc32:crc32-value"
    )
    assert s3_metadata.response_checksum({}) is None
    assert s3_metadata.clean_etag(None) is None
