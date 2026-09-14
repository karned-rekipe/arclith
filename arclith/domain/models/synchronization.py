"""Pull synchronization data. Execution status remains the Job contract."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

type SyncMode = Literal["full", "incremental"]
type SyncOutcome = Literal["created", "updated", "unchanged"]
type SyncErrorCode = Literal[
    "source_failed",
    "invalid_page",
    "missing_external_key",
    "mapping_failed",
    "target_failed",
    "checkpoint_failed",
    "finalization_failed",
    "run_limit",
    "sync_busy",
    "source_version_conflict",
    "cancelled",
    "interrupted",
    "execution_failed",
]
type SyncName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$", strict=True)]
type SyncCursor = Annotated[str, Field(min_length=1, max_length=2048, strict=True)]
type SyncSourceVersion = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$", strict=True)
]


class SyncModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", allow_inf_nan=False
    )

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def validate_schema_version(cls, value: object) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("Sync schema_version must be integer 1")
        return value


class SyncDefinition(SyncModel):
    name: SyncName
    source_version: SyncSourceVersion = "1"
    direction: Literal["pull"] = "pull"
    modes: tuple[SyncMode, ...] = ("full", "incremental")
    external_key: str = Field(
        pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=80, strict=True
    )
    page_size: int = Field(default=100, ge=1, le=1000, strict=True)
    conflict_policy: Literal["source_wins"] = "source_wins"
    missing_policy: Literal["ignore", "deactivate"] = "ignore"
    execution: Literal["job"] = "job"
    max_full_items: int = Field(default=10_000, ge=1, le=100_000, strict=True)
    max_pages: int = Field(default=1000, ge=1, le=10_000, strict=True)

    @field_validator("modes")
    @classmethod
    def validate_modes(cls, value: tuple[SyncMode, ...]) -> tuple[SyncMode, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("Sync modes must be nonempty and unique")
        return tuple(sorted(value))


class SyncRequest(SyncModel):
    schema_version: Literal[1] = 1
    sync_name: SyncName
    source_version: SyncSourceVersion
    mode: SyncMode


class SourcePage[SourceT: BaseModel](SyncModel):
    items: tuple[SourceT, ...] = Field(max_length=1000)
    next_cursor: SyncCursor | None = None
    # Terminal incremental pages supply the watermark for the next pull.
    # It is distinct from next_cursor=None, which only means end of pagination.
    checkpoint_cursor: SyncCursor | None = None


class SyncMapping[TargetT: BaseModel](SyncModel):
    value: TargetT
    owned_fields: tuple[str, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        if len(set(self.owned_fields)) != len(self.owned_fields):
            raise ValueError("Owned fields must be unique")
        if not set(self.owned_fields) <= type(self.value).model_fields.keys():
            raise ValueError("Owned fields must belong to the mapped model")
        return self


class SyncChange[TargetT: BaseModel](SyncModel):
    sync_name: SyncName
    external_id: str = Field(min_length=1, max_length=255, strict=True)
    mapping: SyncMapping[TargetT]


class SyncItemError(SyncModel):
    code: SyncErrorCode
    page: int = Field(ge=0, strict=True)
    item: int | None = Field(default=None, ge=0, strict=True)


class SyncReport(SyncModel):
    schema_version: Literal[1] = 1
    job_id: str = Field(min_length=1, max_length=36, strict=True)
    sync_name: SyncName
    complete: bool = Field(default=False, strict=True)
    pages: int = Field(default=0, ge=0, strict=True)
    created: int = Field(default=0, ge=0, strict=True)
    updated: int = Field(default=0, ge=0, strict=True)
    unchanged: int = Field(default=0, ge=0, strict=True)
    deactivated: int = Field(default=0, ge=0, strict=True)
    skipped: int = Field(default=0, ge=0, strict=True)
    failed: int = Field(default=0, ge=0, strict=True)
    errors: tuple[SyncItemError, ...] = Field(default=(), max_length=20)

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str) -> str:
        return str(UUID(value))

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.unchanged + self.skipped + self.failed


class SyncCheckpoint(SyncModel):
    schema_version: Literal[1] = 1
    sync_name: SyncName
    source_version: SyncSourceVersion
    version: int = Field(default=0, ge=0, strict=True)
    last_successful_cursor: SyncCursor | None = None
    last_success_at: AwareDatetime | None = None
    last_report: SyncReport | None = None

    @field_validator("last_success_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None
