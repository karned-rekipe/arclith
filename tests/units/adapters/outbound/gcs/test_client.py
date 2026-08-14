import base64
import builtins
import sys
from types import ModuleType
from typing import Any

import pytest

from arclith.adapters.outbound.gcs import client as gcs_client
from arclith.adapters.outbound.gcs.config import ResolvedGCSConfig
from arclith.domain.ports.outbound.file_storage import (
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.gcs.fakes import GCSProviderError


def test_safe_create_gcs_client_attaches_key_to_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = FileStorageUnavailable("explicit setup error")

    def create_client(_resolved: ResolvedGCSConfig) -> object:
        raise expected

    monkeypatch.setattr(gcs_client, "create_gcs_client", create_client)

    with pytest.raises(FileStorageUnavailable) as exc_info:
        gcs_client.safe_create_gcs_client(_resolved_config(), key="docs/readme.txt")

    assert exc_info.value is expected
    assert exc_info.value.key == "docs/readme.txt"


def test_safe_create_gcs_client_maps_setup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def create_client(_resolved: ResolvedGCSConfig) -> object:
        raise GCSProviderError(403)

    monkeypatch.setattr(gcs_client, "create_gcs_client", create_client)

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        gcs_client.safe_create_gcs_client(_resolved_config(), key="docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


def test_create_gcs_client_requires_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"google.cloud", "google.oauth2"}:
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(FileStorageUnavailable, match=r"arclith\[gcs\]"):
        gcs_client.create_gcs_client(_resolved_config())


def test_create_gcs_client_uses_sdk_client_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected_client = object()
    _install_fake_google_modules(monkeypatch, captured, expected_client)

    client = gcs_client.create_gcs_client(
        _resolved_config(prefix="uploads", project_id="project-a")
    )

    assert client is expected_client
    assert captured["client"] == {"project": "project-a"}


def test_create_gcs_client_uses_json_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected_client = object()
    _install_fake_google_modules(monkeypatch, captured, expected_client)

    gcs_client.create_gcs_client(
        _resolved_config(
            credentials_json='{"type":"service_account","project_id":"demo"}'
        )
    )

    assert captured["service_account_info"] == {
        "type": "service_account",
        "project_id": "demo",
    }
    assert captured["client"] == {"credentials": "credentials-from-info"}


def test_create_gcs_client_uses_encoded_env_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected_client = object()
    _install_fake_google_modules(monkeypatch, captured, expected_client)
    encoded = base64.b64encode(b'{"type":"service_account"}').decode()
    monkeypatch.setenv("ARCLITH_GCS_CREDENTIALS_JSON_B64", encoded)

    gcs_client.create_gcs_client(_resolved_config())

    assert captured["service_account_info"] == {"type": "service_account"}
    assert captured["client"] == {"credentials": "credentials-from-info"}


def test_safe_create_gcs_client_maps_invalid_credentials_with_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_google_modules(monkeypatch, captured, object())

    with pytest.raises(FileStorageUnavailable) as exc_info:
        gcs_client.safe_create_gcs_client(
            _resolved_config(credentials_json="not-json"),
            key="docs/readme.txt",
        )

    assert exc_info.value.key == "docs/readme.txt"


def _install_fake_google_modules(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, Any],
    expected_client: object,
) -> None:
    storage_module = ModuleType("google.cloud.storage")
    oauth2_module = ModuleType("google.oauth2")
    service_account_module = ModuleType("google.oauth2.service_account")
    cloud_module = ModuleType("google.cloud")
    google_module = ModuleType("google")

    class FakeStorageClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs

        def __new__(cls, **kwargs: Any) -> object:
            instance = super().__new__(cls)
            FakeStorageClient.__init__(instance, **kwargs)
            return expected_client

    class FakeCredentials:
        @staticmethod
        def from_service_account_info(info: dict[str, Any]) -> str:
            captured["service_account_info"] = info
            return "credentials-from-info"

        @staticmethod
        def from_service_account_file(path: str) -> str:
            captured["service_account_file"] = path
            return "credentials-from-file"

    storage_module.Client = FakeStorageClient  # type: ignore[attr-defined]
    service_account_module.Credentials = FakeCredentials  # type: ignore[attr-defined]
    cloud_module.storage = storage_module  # type: ignore[attr-defined]
    oauth2_module.service_account = service_account_module  # type: ignore[attr-defined]
    google_module.cloud = cloud_module  # type: ignore[attr-defined]
    google_module.oauth2 = oauth2_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_module)
    monkeypatch.setitem(
        sys.modules, "google.oauth2.service_account", service_account_module
    )


def _resolved_config(**overrides: Any) -> ResolvedGCSConfig:
    values: dict[str, Any] = {
        "bucket_name": "arclith-files",
        "prefix": "",
        "project_id": None,
        "credentials_path": None,
        "credentials_json": None,
        "credentials_json_b64": None,
    }
    values.update(overrides)
    return ResolvedGCSConfig(**values)
