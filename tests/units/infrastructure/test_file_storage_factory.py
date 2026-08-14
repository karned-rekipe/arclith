from pathlib import Path

import pytest

from arclith import Arclith
from arclith.adapters.outbound.azure_blob import AzureBlobFileStorage
from arclith.adapters.outbound.filesystem import FilesystemFileStorage
from arclith.adapters.outbound.gcs import GCSFileStorage
from arclith.adapters.outbound.s3 import S3FileStorage
from arclith.domain.ports.outbound.file_storage import FileStoragePort
from arclith.infrastructure.config import AppConfig, StorageSettings
from arclith.infrastructure.file_storage_factory import (
    FileStorageRegistry,
    build_file_storage,
    default_file_storage_registry,
)


def test_build_file_storage_returns_filesystem_adapter(logger, tmp_path: Path) -> None:
    config = AppConfig.model_validate({
        "adapters": {
            "storage": {
                "adapter": "filesystem",
                "root_path": str(tmp_path),
                "prefix": "uploads",
            }
        }
    })

    storage = build_file_storage(config, logger)

    assert isinstance(storage, FilesystemFileStorage)


def test_build_file_storage_returns_s3_adapter(logger) -> None:
    config = AppConfig.model_validate({
        "adapters": {
            "storage": {
                "adapter": "s3",
                "bucket_name": "arclith-files",
                "prefix": "uploads",
                "region_name": "eu-west-3",
                "endpoint_url": "http://127.0.0.1:9000",
                "force_path_style": True,
            }
        }
    })

    storage = build_file_storage(config, logger)

    assert isinstance(storage, S3FileStorage)


def test_build_file_storage_returns_gcs_adapter(logger) -> None:
    config = AppConfig.model_validate(
        {
            "adapters": {
                "storage": {
                    "adapter": "gcs",
                    "bucket_name": "arclith-files",
                    "prefix": "uploads",
                    "project_id": "project-a",
                }
            }
        }
    )

    storage = build_file_storage(config, logger)

    assert isinstance(storage, GCSFileStorage)


def test_build_file_storage_returns_azure_blob_adapter(logger) -> None:
    config = AppConfig.model_validate(
        {
            "adapters": {
                "storage": {
                    "adapter": "azure-blob",
                    "account_url": "https://account.blob.core.windows.net",
                    "container_name": "arclith-files",
                    "prefix": "uploads",
                    "connection_string": "UseDevelopmentStorage=true",
                    "use_default_credential": False,
                }
            }
        }
    )

    storage = build_file_storage(config, logger)

    assert isinstance(storage, AzureBlobFileStorage)


def test_build_file_storage_requires_storage_config(logger) -> None:
    with pytest.raises(ValueError, match="adapters.storage"):
        build_file_storage(AppConfig(), logger)


def test_custom_file_storage_registry_builds_adapter(logger) -> None:
    expected = object()
    config = AppConfig.model_construct(
        adapters=AppConfig().adapters.model_copy(
            update={"storage": StorageSettings.model_construct(adapter="custom")}
        )
    )
    registry = FileStorageRegistry().register(
        "custom",
        lambda cfg, log: expected,  # type: ignore[return-value]
    )

    storage = build_file_storage(config, logger, registry=registry)

    assert storage is expected


def test_default_file_storage_registry_rejects_unknown_adapter(logger) -> None:
    config = AppConfig.model_construct(
        adapters=AppConfig().adapters.model_copy(
            update={"storage": StorageSettings.model_construct(adapter="custom")}
        )
    )

    with pytest.raises(ValueError, match="custom"):
        default_file_storage_registry().build(config, logger)


def test_arclith_builds_configured_file_storage(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "adapters" / "outbound"
    config_dir.mkdir(parents=True)
    (tmp_path / "config" / "adapters" / "adapters.yaml").write_text(
        "logger: console\n"
        "repository: memory\n"
        "observability:\n"
        "  enabled: []\n",
        encoding="utf-8",
    )
    (config_dir / "storage.yaml").write_text(
        "adapter: filesystem\n"
        f"root_path: {tmp_path / 'files'}\n"
        "prefix: uploads\n"
        "create_root: true\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    app = Arclith(tmp_path / "config")
    storage = app.file_storage()

    assert isinstance(storage, FileStoragePort)
    assert isinstance(storage, FilesystemFileStorage)
