from typing import TYPE_CHECKING

from arclith.adapters.inbound.schemas.base_schema import BaseSchema
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.adapters.outbound.mongodb.config import MongoDBConfig
from arclith.application.services.base_service import BaseService
from arclith.arclith import Arclith
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.adapter_registry import AdapterRegistry
from arclith.infrastructure.config import AppConfig, LMSettings, export_config_yaml, load_config, load_config_dir, load_config_file
from arclith.infrastructure.project_layout import ProjectLayout, ProjectLayoutKind, canonical_project_layout
from arclith.infrastructure.repository_factory import RepositoryRegistry, build_repository, default_repository_registry

if TYPE_CHECKING:  # pragma: no cover - for static type checkers only
    from arclith.adapters.outbound.console.logger import ConsoleLogger as _ConsoleLogger, ConsoleLogger  # noqa: F401

__all__ = [
    "Entity",
    "Repository",
    "Logger",
    "LogLevel",
    "BaseService",
    "BaseSchema",
    "ConsoleLogger",
    "InMemoryRepository",
    "MongoDBConfig",
    "AppConfig",
    "LMSettings",
    "load_config",
    "load_config_dir",
    "load_config_file",
    "export_config_yaml",
    "AdapterRegistry",
    "RepositoryRegistry",
    "build_repository",
    "default_repository_registry",
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
        from arclith.adapters.outbound.console.logger import ConsoleLogger as _ConsoleLoggerRuntime

        globals()["ConsoleLogger"] = _ConsoleLoggerRuntime
        return _ConsoleLoggerRuntime
    if name == "build_pydantic_ai_model":
        from arclith.infrastructure.lm import build_pydantic_ai_model as _build_pydantic_ai_model

        globals()["build_pydantic_ai_model"] = _build_pydantic_ai_model
        return _build_pydantic_ai_model
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
