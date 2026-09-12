from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class GuidePlanError(ValueError):
    """Raised when guided answers cannot form a safe project plan."""


class GuideCancelled(Exception):
    """Raised when the user leaves an interactive prompt."""


class ProjectIntent(StrEnum):
    MINIMAL = "minimal"
    API_CRUD = "api-crud"
    API_CUSTOM = "api-custom"
    MCP = "mcp"
    AGENT = "agent"
    WORKER = "worker"


class RepositoryChoice(StrEnum):
    MEMORY = "memory"
    MONGODB = "mongodb"
    POSTGRESQL = "postgresql"


@dataclass(frozen=True)
class GuideChoice:
    title: str
    value: str
    description: str
    disabled: str | None = None
    checked: bool = False


@dataclass(frozen=True)
class GuideStep:
    title: str
    command: str
    args: dict[str, Any]
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ProjectPlan:
    target_dir: Path
    intent: ProjectIntent | None
    steps: tuple[GuideStep, ...]
    creates_project: bool


@dataclass(frozen=True)
class ProjectExecutionResult:
    root: Path
    executed_commands: tuple[str, ...]


@dataclass(frozen=True)
class NewProjectAnswers:
    parent_dir: Path
    project_name: str
    intent: ProjectIntent
    entity: str | None
    usecase: str | None
    repository: RepositoryChoice | None
    transport_port: int | None
    public_path: str | None


@dataclass(frozen=True)
class ProjectFeature:
    name: str
    entity: str
    blueprint: str


@dataclass(frozen=True)
class ProjectOverview:
    root: Path
    name: str
    package: str
    entities: tuple[str, ...]
    usecases: tuple[str, ...]
    features: tuple[ProjectFeature, ...]
    adapters: tuple[str, ...]
    issues: tuple[str, ...]

    def has_adapter(self, capability: str, adapter: str) -> bool:
        return f"{capability}/{adapter}" in self.adapters
