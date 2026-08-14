from collections.abc import Callable

from arclith.domain.ports.outbound.file_storage import FileStoragePort
from arclith.domain.ports.outbound.logger import Logger
from arclith.infrastructure.config import AppConfig

FileStorageFactory = Callable[[AppConfig, Logger], FileStoragePort]


class FileStorageRegistry:
    """Registry mapping file-storage adapter names to factories."""

    def __init__(self) -> None:
        self._factories: dict[str, FileStorageFactory] = {}

    def register(self, name: str, factory: FileStorageFactory) -> "FileStorageRegistry":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, logger: Logger) -> FileStoragePort:
        settings = config.adapters.storage
        if settings is None:
            raise ValueError("adapters.storage is required to build file storage")
        if settings.adapter not in self._factories:
            raise ValueError(
                f"File storage adapter '{settings.adapter}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[settings.adapter](config, logger)


def build_file_storage(
    config: AppConfig,
    logger: Logger,
    *,
    registry: FileStorageRegistry | None = None,
) -> FileStoragePort:
    if registry is None:
        return default_file_storage_registry().build(config, logger)
    return registry.build(config, logger)


def default_file_storage_registry() -> FileStorageRegistry:
    return (
        FileStorageRegistry()
        .register("filesystem", _build_filesystem_file_storage)
        .register("s3", _build_s3_file_storage)
        .register("gcs", _build_gcs_file_storage)
    )


def _build_filesystem_file_storage(config: AppConfig, _logger: Logger) -> FileStoragePort:
    from arclith.adapters.outbound.filesystem import FilesystemFileStorage, FilesystemStorageConfig

    settings = config.adapters.storage
    if settings is None:
        raise ValueError("Filesystem storage settings are required")
    if settings.root_path is None:
        raise ValueError("Filesystem storage root_path is required")

    return FilesystemFileStorage(
        FilesystemStorageConfig(
            root_path=settings.root_path,
            prefix=settings.prefix,
            create_root=settings.create_root,
        )
    )


def _build_s3_file_storage(config: AppConfig, _logger: Logger) -> FileStoragePort:
    from arclith.adapters.outbound.s3 import S3FileStorage, S3StorageConfig

    settings = config.adapters.storage
    if settings is None:
        raise ValueError("S3 storage settings are required")

    return S3FileStorage(
        S3StorageConfig(
            bucket_name=settings.bucket_name,
            prefix=settings.prefix,
            region_name=settings.region_name,
            endpoint_url=settings.endpoint_url,
            force_path_style=settings.force_path_style,
            multitenant=settings.multitenant,
        )
    )


def _build_gcs_file_storage(config: AppConfig, _logger: Logger) -> FileStoragePort:
    from arclith.adapters.outbound.gcs import GCSFileStorage, GCSStorageConfig

    settings = config.adapters.storage
    if settings is None:
        raise ValueError("GCS storage settings are required")

    return GCSFileStorage(
        GCSStorageConfig(
            bucket_name=settings.bucket_name,
            prefix=settings.prefix,
            project_id=settings.project_id,
            multitenant=settings.multitenant,
        )
    )
