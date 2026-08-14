import pytest

from arclith.adapters.outbound.gcs import errors as gcs_errors
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.gcs.fakes import GCSProviderError


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (GCSProviderError(404), FileStorageNotFound),
        (GCSProviderError(403), FileStoragePermissionDenied),
        (GCSProviderError(412), FileStorageConflict),
        (GCSProviderError(503), FileStorageUnavailable),
        (GCSProviderError(418), FileStorageUnavailable),
    ],
)
def test_raise_gcs_storage_error_maps_provider_codes(
    error: Exception,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        gcs_errors.raise_gcs_storage_error(error, key="docs/readme.txt")


def test_raise_gcs_storage_error_maps_provider_names() -> None:
    class NotFound(Exception):
        pass

    class DefaultCredentialsError(Exception):
        pass

    class PreconditionFailed(Exception):
        pass

    with pytest.raises(FileStorageNotFound):
        gcs_errors.raise_gcs_storage_error(NotFound(), key="docs/readme.txt")
    with pytest.raises(FileStoragePermissionDenied):
        gcs_errors.raise_gcs_storage_error(
            DefaultCredentialsError(), key="docs/readme.txt"
        )
    with pytest.raises(FileStorageConflict):
        gcs_errors.raise_gcs_storage_error(PreconditionFailed(), key="docs/readme.txt")


def test_gcs_error_code_parsing_tolerates_incomplete_payloads() -> None:
    class MissingCodeError(Exception):
        pass

    class ResponseWithStatusCode(Exception):
        response = type("Response", (), {"status_code": 429})()

    class ResponseWithStatus(Exception):
        response = type("Response", (), {"status": 500})()

    assert gcs_errors.provider_error_code(MissingCodeError()) is None
    assert gcs_errors.provider_error_code(ResponseWithStatusCode()) == "429"
    assert gcs_errors.provider_error_code(ResponseWithStatus()) == "500"
