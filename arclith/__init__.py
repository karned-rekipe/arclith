from typing import TYPE_CHECKING

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.adapters.bidirectional.webhook import (
    WebhookCallbackSender,
    WebhookChannelAdapter,
    WebhookError,
    WebhookErrorResponse,
    WebhookIncomingPayload,
    WebhookInvalidPayload,
    WebhookMissingEventId,
    WebhookPayloadTooLarge,
    WebhookResponse,
    WebhookResponseModeError,
    WebhookSignatureVerifier,
    WebhookUnsupportedMediaType,
    build_webhook_router,
    sign_webhook_payload,
)
from arclith.adapters.inbound.schemas.base_schema import BaseSchema
from arclith.adapters.outbound.azure_blob import (
    AzureBlobFileStorage,
    AzureBlobStorageConfig,
)
from arclith.adapters.outbound.deterministic import DeterministicEmbeddingAdapter
from arclith.adapters.outbound.filesystem import (
    FilesystemFileStorage,
    FilesystemStorageConfig,
)
from arclith.adapters.outbound.gcs import GCSFileStorage, GCSStorageConfig
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.adapters.outbound.memory.vector_store import MemoryVectorStore
from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.adapters.outbound.qdrant import QdrantVectorStore
from arclith.adapters.outbound.s3 import S3FileStorage, S3StorageConfig
from arclith.application.channel import ChannelDispatcher
from arclith.application.command_bus import CommandDispatcher, CommandEnvelope
from arclith.application.services.base_service import BaseService
from arclith.arclith import Arclith
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelError,
    ChannelIdentityNotResolved,
    ChannelRateLimited,
    ChannelUnauthorized,
    ChannelUnavailable,
    InvalidChannelSignature,
    UnsupportedChannelEvent,
)
from arclith.domain.models.channel import (
    ChannelAttachment,
    ChannelDeliveryReceipt,
    ChannelDispatchResult,
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelIncomingMessage,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)
from arclith.domain.models.entity import Entity
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.inbound.command_bus import CommandHandler
from arclith.domain.ports.outbound.channel import (
    ChannelEventStore,
    ChannelIdentityResolver,
    ChannelSender,
)
from arclith.domain.ports.outbound.command_bus import CommandPublisher
from arclith.domain.ports.outbound.embedding import (
    EmbeddingAuthenticationError,
    EmbeddingDimensionMismatch,
    EmbeddingError,
    EmbeddingInvalidInput,
    EmbeddingPort,
    EmbeddingRateLimitError,
    EmbeddingResponse,
    EmbeddingResult,
    EmbeddingText,
    EmbeddingUnavailable,
    EmbeddingUsage,
    validate_embedding_inputs,
)
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
    ContextPropagatorPort,
    CorrelationContextPort,
    LogRecordPort,
    MetricPort,
    ObservabilityRuntimePort,
    TraceAnonymizer,
    TracePort,
    TraceSpan,
)
from arclith.domain.ports.outbound.repository import Repository
from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchHit,
    VectorSearchQuery,
    VectorStoreCollectionNotFound,
    VectorStoreDimensionMismatch,
    VectorStoreError,
    VectorStoreInvalidPayload,
    VectorStorePermissionDenied,
    VectorStorePort,
    VectorStoreUnavailable,
)
from arclith.infrastructure.adapter_registry import AdapterRegistry
from arclith.infrastructure.config import (
    AppConfig,
    LangGraphPersistenceSettings,
    LMSettings,
    OpenTelemetrySettings,
    WebhookChannelSettings,
    export_config_yaml,
    load_config_dir,
    load_config_file,
)
from arclith.infrastructure.channel_factory import (
    ChannelSenderRegistry,
    build_channel_sender,
    default_channel_sender_registry,
)
from arclith.infrastructure.embedding_factory import (
    EmbeddingRegistry,
    build_embedding,
    default_embedding_registry,
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
from arclith.infrastructure.vector_store_factory import (
    VectorStoreRegistry,
    build_vector_store,
    default_vector_store_registry,
)

if TYPE_CHECKING:  # pragma: no cover - for static type checkers only
    from arclith.adapters.outbound.console.logger import ConsoleLogger  # noqa: F401

__all__ = [
    "ChannelAttachment",
    "ChannelDeliveryFailed",
    "ChannelDeliveryReceipt",
    "ChannelDispatcher",
    "ChannelDispatchResult",
    "ChannelError",
    "ChannelEventStore",
    "ChannelHandlerResult",
    "ChannelIdentity",
    "ChannelIdentityNotResolved",
    "ChannelIdentityResolver",
    "ChannelIncomingMessage",
    "ChannelMessageHandler",
    "ChannelOutgoingMessage",
    "ChannelRateLimited",
    "ChannelSender",
    "ChannelSenderRegistry",
    "ChannelUnauthorized",
    "ChannelUnavailable",
    "InvalidChannelSignature",
    "MemoryChannel",
    "MemoryChannelIdentityResolver",
    "ResolvedChannelIdentity",
    "UnsupportedChannelEvent",
    "WebhookCallbackSender",
    "WebhookChannelAdapter",
    "WebhookChannelSettings",
    "WebhookError",
    "WebhookErrorResponse",
    "WebhookIncomingPayload",
    "WebhookInvalidPayload",
    "WebhookMissingEventId",
    "WebhookPayloadTooLarge",
    "WebhookResponse",
    "WebhookResponseModeError",
    "WebhookSignatureVerifier",
    "WebhookUnsupportedMediaType",
    "build_webhook_router",
    "build_channel_sender",
    "default_channel_sender_registry",
    "sign_webhook_payload",
    "Entity",
    "Repository",
    "EmbeddingPort",
    "EmbeddingText",
    "EmbeddingResult",
    "EmbeddingUsage",
    "EmbeddingResponse",
    "EmbeddingError",
    "EmbeddingUnavailable",
    "EmbeddingAuthenticationError",
    "EmbeddingRateLimitError",
    "EmbeddingInvalidInput",
    "EmbeddingDimensionMismatch",
    "validate_embedding_inputs",
    "DeterministicEmbeddingAdapter",
    "VectorStorePort",
    "VectorPoint",
    "VectorSearchQuery",
    "VectorSearchHit",
    "VectorStoreError",
    "VectorStoreUnavailable",
    "VectorStoreCollectionNotFound",
    "VectorStoreDimensionMismatch",
    "VectorStorePermissionDenied",
    "VectorStoreInvalidPayload",
    "MemoryVectorStore",
    "QdrantVectorStore",
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
    "MetricPort",
    "CorrelationContextPort",
    "ContextPropagatorPort",
    "LogRecordPort",
    "ObservabilityRuntimePort",
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
    "OpenTelemetrySettings",
    "LangGraphPersistenceSettings",
    "load_config_dir",
    "load_config_file",
    "export_config_yaml",
    "AdapterRegistry",
    "RepositoryRegistry",
    "build_repository",
    "default_repository_registry",
    "EmbeddingRegistry",
    "build_embedding",
    "default_embedding_registry",
    "VectorStoreRegistry",
    "build_vector_store",
    "default_vector_store_registry",
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
