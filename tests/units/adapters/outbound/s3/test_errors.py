import pytest

from arclith.adapters.outbound.s3 import errors as s3_errors
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.s3.fakes import S3ProviderError


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (S3ProviderError("NoSuchKey"), FileStorageNotFound),
        (S3ProviderError("AccessDenied"), FileStoragePermissionDenied),
        (S3ProviderError("PreconditionFailed"), FileStorageConflict),
        (S3ProviderError("NoSuchBucket"), FileStorageUnavailable),
        (S3ProviderError("UnexpectedProviderCode"), FileStorageUnavailable),
    ],
)
def test_raise_s3_storage_error_maps_provider_errors(
    error: Exception,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        s3_errors.raise_s3_storage_error(error, key="docs/readme.txt")


def test_s3_error_code_parsing_tolerates_incomplete_payloads() -> None:
    class ResponseIsNotMappingError(Exception):
        response = "not-a-mapping"

    class ErrorPayloadIsNotMappingError(Exception):
        response = {"Error": "not-a-mapping"}

    class CodeIsMissingError(Exception):
        response = {"Error": {}}

    assert s3_errors.provider_error_code(ResponseIsNotMappingError()) is None
    assert s3_errors.provider_error_code(ErrorPayloadIsNotMappingError()) is None
    assert s3_errors.provider_error_code(CodeIsMissingError()) is None
