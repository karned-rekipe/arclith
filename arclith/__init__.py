from typing import TYPE_CHECKING

from arclith.adapters.inbound.schemas.base_schema import BaseSchema
from arclith.adapters.outbound.azure_blob import (
    AzureBlobFileStorage,
    AzureBlobStorageConfig,
)
from arclith.adapters.outbound.filesystem import (
    FilesystemFileStorage,
    FilesystemStorageConfig,
)
from arclith.adapters.outbound.gcs import GCSFileStorage, GCSStorageConfig
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.adapters.outbound.s3 import S3FileStorage, S3StorageConfig
from arclith.application.command_bus import CommandDispatcher, CommandEnvelope
from arclith.application.services.base_service import BaseService
from arclith.arclith import Arclith
from arclith.domain.models.entity import Entity
from arclith.domain.ports.inbound.command_bus import CommandHandler
from arclith.domain.ports.outbound.command_bus import CommandPublisher
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageError,
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStoragePort,
    FileStorageUnavailable,
    StoredObject,
    StoredObjectMetadata,
    StoredObjectStream,
    normalize_storage_key,
)
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.domain.ports.outbound.observability import (
    TraceAnonymizer,
    TracePort,
    TraceSpan,
)
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.adapter_registry import AdapterRegistry
from arclith.infrastructure.config import (
    AppConfig,
    LangGraphPersistenceSettings,
    LMSettings,
    export_config_yaml,
    load_config_dir,
    load_config_file,
)
from arclith.infrastructure.file_storage_factory import (
    FileStorageRegistry,
    build_file_storage,
    default_file_storage_registry,
)
from arclith.infrastructure.langgraph_persistence_factory import (
    LangGraphPersistenceRegistry,
    build_langgraph_persistence,
    default_langgraph_persistence_registry,
    render_langgraph_namespace,
)
from arclith.infrastructure.project_layout import (
    ProjectLayout,
    ProjectLayoutKind,
    canonical_project_layout,
)
from arclith.infrastructure.repository_factory import (
    RepositoryRegistry,
    build_repository,
    default_repository_registry,
)

if TYPE_CHECKING:  # pragma: no cover - for static type checkers only
    from arclith.adapters.outbound.console.logger import ConsoleLogger  # noqa: F401

__all__ = [
    "Entity",
    "Repository",
    "FileStoragePort",
    "StoredObject",
    "StoredObjectMetadata",
    "StoredObjectStream",
    "FileStorageError",
    "FileStorageInvalidKey",
    "FileStorageNotFound",
    "FileStorageConflict",
    "FileStorageUnavailable",
    "FileStoragePermissionDenied",
    "normalize_storage_key",
    "FilesystemFileStorage",
    "FilesystemStorageConfig",
    "S3FileStorage",
    "S3StorageConfig",
    "AzureBlobFileStorage",
    "AzureBlobStorageConfig",
    "GCSFileStorage",
    "GCSStorageConfig",
    "Logger",
    "LogLevel",
    "TracePort",
    "TraceSpan",
    "TraceAnonymizer",
    "BaseService",
    "CommandDispatcher",
    "CommandEnvelope",
    "CommandHandler",
    "CommandPublisher",
    "BaseSchema",
    "ConsoleLogger",
    "InMemoryRepository",
    "MongoDBConfig",
    "AppConfig",
    "LMSettings",
    "LangGraphPersistenceSettings",
    "load_config_dir",
    "load_config_file",
    "export_config_yaml",
    "AdapterRegistry",
    "RepositoryRegistry",
    "build_repository",
    "default_repository_registry",
    "FileStorageRegistry",
    "build_file_storage",
    "default_file_storage_registry",
    "LangGraphPersistenceRegistry",
    "build_langgraph_persistence",
    "default_langgraph_persistence_registry",
    "render_langgraph_namespace",
    "ProjectLayout",
    "ProjectLayoutKind",
    "canonical_project_layout",
    "Arclith",
    "build_pydantic_ai_model",
]


def __getattr__(name):
    """
    Lazily import objects that may have side effects at import time.

    This prevents side-effectful modules (such as the ConsoleLogger's Loguru
    configuration) from being imported merely by doing ``import arclith``.
    """
    if name == "ConsoleLogger":
        from arclith.adapters.outbound.console.logger import (
            ConsoleLogger as _ConsoleLoggerRuntime,
        )

        globals()["ConsoleLogger"] = _ConsoleLoggerRuntime
        return _ConsoleLoggerRuntime
    if name == "build_pydantic_ai_model":
        from arclith.infrastructure.lm import (
            build_pydantic_ai_model as _build_pydantic_ai_model,
        )

        globals()["build_pydantic_ai_model"] = _build_pydantic_ai_model
        return _build_pydantic_ai_model
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
