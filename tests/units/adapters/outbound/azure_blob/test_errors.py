from arclith.adapters.outbound.azure_blob.errors import (
    azure_blob_storage_error_from_provider,
    is_not_found_error,
    provider_error_code,
)
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.azure_blob.fakes import AzureProviderError


def test_provider_error_code_reads_error_code() -> None:
    assert provider_error_code(AzureProviderError("BlobNotFound")) == "BlobNotFound"


def test_provider_error_code_reads_status_code() -> None:
    assert provider_error_code(AzureProviderError(status_code=404)) == "404"


def test_provider_error_code_reads_response_status() -> None:
    response = type("Response", (), {"status": 503})()
    error = type("AzureError", (Exception,), {"response": response})()

    assert provider_error_code(error) == "503"


def test_is_not_found_error_matches_code_and_type() -> None:
    assert is_not_found_error(AzureProviderError("BlobNotFound")) is True

    error = type("ResourceNotFoundError", (Exception,), {})()

    assert is_not_found_error(error) is True


def test_azure_blob_storage_error_mapping() -> None:
    cases = [
        (AzureProviderError("BlobNotFound"), FileStorageNotFound),
        (
            AzureProviderError("AuthorizationPermissionMismatch", status_code=403),
            FileStoragePermissionDenied,
        ),
        (AzureProviderError("BlobAlreadyExists", status_code=409), FileStorageConflict),
        (AzureProviderError("ServerBusy", status_code=503), FileStorageUnavailable),
        (AzureProviderError("Unexpected"), FileStorageUnavailable),
    ]

    for error, expected_type in cases:
        mapped = azure_blob_storage_error_from_provider(error, key="docs/readme.txt")

        assert isinstance(mapped, expected_type)
        assert mapped.key == "docs/readme.txt"
