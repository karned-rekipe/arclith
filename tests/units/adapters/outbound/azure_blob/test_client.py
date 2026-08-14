import importlib.abc
import sys
from types import ModuleType
from typing import Any

import pytest

from arclith.adapters.outbound.azure_blob.client import (
    create_azure_blob_content_settings,
    create_azure_blob_service_client,
    safe_create_azure_blob_service_client,
)
from arclith.adapters.outbound.azure_blob.config import ResolvedAzureBlobConfig
from arclith.domain.ports.outbound.file_storage import FileStorageUnavailable


def test_create_azure_blob_service_client_requires_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in list(sys.modules):
        if module_name == "azure" or module_name.startswith("azure."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    class BlockAzureExtras(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname == "azure" or fullname.startswith("azure."):
                raise ModuleNotFoundError(fullname)
            return None

    blocker = BlockAzureExtras()
    sys.meta_path.insert(0, blocker)
    try:
        with pytest.raises(FileStorageUnavailable, match=r"arclith\[azure-blob\]"):
            create_azure_blob_service_client(
                ResolvedAzureBlobConfig(
                    account_url="https://account.blob.core.windows.net",
                    container_name="arclith-files",
                    prefix="",
                )
            )
    finally:
        sys.meta_path.remove(blocker)


def test_create_azure_blob_service_client_uses_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = _install_fake_azure_modules(monkeypatch)

    client = create_azure_blob_service_client(
        ResolvedAzureBlobConfig(
            account_url=None,
            container_name="arclith-files",
            prefix="",
            connection_string="UseDevelopmentStorage=true",
        )
    )

    assert isinstance(client, modules["FakeBlobServiceClient"])
    assert client.connection_string == "UseDevelopmentStorage=true"


def test_create_azure_blob_service_client_uses_account_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = _install_fake_azure_modules(monkeypatch)

    client = create_azure_blob_service_client(
        ResolvedAzureBlobConfig(
            account_url="https://account.blob.core.windows.net",
            container_name="arclith-files",
            prefix="",
            account_key="account-key",
        )
    )

    assert isinstance(client.credential, modules["FakeAzureNamedKeyCredential"])
    assert client.credential.name == "account"
    assert client.credential.key == "account-key"


def test_create_azure_blob_service_client_uses_sas_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = _install_fake_azure_modules(monkeypatch)

    client = create_azure_blob_service_client(
        ResolvedAzureBlobConfig(
            account_url="https://account.blob.core.windows.net",
            container_name="arclith-files",
            prefix="",
            sas_token="?sig=token",
        )
    )

    assert isinstance(client.credential, modules["FakeAzureSasCredential"])
    assert client.credential.token == "sig=token"


def test_create_azure_blob_service_client_uses_default_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = _install_fake_azure_modules(monkeypatch)

    client = create_azure_blob_service_client(
        ResolvedAzureBlobConfig(
            account_url="https://account.blob.core.windows.net",
            container_name="arclith-files",
            prefix="",
            use_default_credential=True,
        )
    )

    assert isinstance(client.credential, modules["FakeDefaultAzureCredential"])


def test_safe_create_azure_blob_service_client_sets_key_on_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_azure_modules(monkeypatch)

    with pytest.raises(FileStorageUnavailable) as exc_info:
        safe_create_azure_blob_service_client(
            ResolvedAzureBlobConfig(
                account_url="https://account.blob.core.windows.net",
                container_name="arclith-files",
                prefix="",
                account_key="account-key",
                sas_token="sig=token",
            ),
            key="docs/readme.txt",
        )

    assert "ambiguous" in str(exc_info.value)
    assert exc_info.value.key == "docs/readme.txt"


def test_create_azure_blob_content_settings_uses_azure_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = _install_fake_azure_modules(monkeypatch)

    settings = create_azure_blob_content_settings("text/plain")

    assert isinstance(settings, modules["FakeContentSettings"])
    assert settings.content_type == "text/plain"


def _install_fake_azure_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    azure = ModuleType("azure")
    core = ModuleType("azure.core")
    credentials = ModuleType("azure.core.credentials")
    identity = ModuleType("azure.identity")
    storage = ModuleType("azure.storage")
    blob = ModuleType("azure.storage.blob")

    class FakeAzureNamedKeyCredential:
        def __init__(self, *, name: str, key: str) -> None:
            self.name = name
            self.key = key

    class FakeAzureSasCredential:
        def __init__(self, token: str) -> None:
            self.token = token

    class FakeDefaultAzureCredential:
        pass

    class FakeContentSettings:
        def __init__(self, *, content_type: str) -> None:
            self.content_type = content_type

    class FakeBlobServiceClient:
        def __init__(
            self,
            *,
            account_url: str | None = None,
            credential: Any | None = None,
        ) -> None:
            self.account_url = account_url
            self.credential = credential
            self.connection_string: str | None = None

        @classmethod
        def from_connection_string(cls, *, conn_str: str) -> "FakeBlobServiceClient":
            client = cls()
            client.connection_string = conn_str
            return client

    credentials.AzureNamedKeyCredential = FakeAzureNamedKeyCredential
    credentials.AzureSasCredential = FakeAzureSasCredential
    identity.DefaultAzureCredential = FakeDefaultAzureCredential
    blob.BlobServiceClient = FakeBlobServiceClient
    blob.ContentSettings = FakeContentSettings

    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.core", core)
    monkeypatch.setitem(sys.modules, "azure.core.credentials", credentials)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.storage", storage)
    monkeypatch.setitem(sys.modules, "azure.storage.blob", blob)

    return {
        "FakeAzureNamedKeyCredential": FakeAzureNamedKeyCredential,
        "FakeAzureSasCredential": FakeAzureSasCredential,
        "FakeDefaultAzureCredential": FakeDefaultAzureCredential,
        "FakeBlobServiceClient": FakeBlobServiceClient,
        "FakeContentSettings": FakeContentSettings,
    }
