from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

LangGraphStreamMode = Literal[
    "values", "updates", "custom", "messages", "checkpoints", "tasks", "debug"
]


def _normalize_adapter(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("la valeur ne doit pas etre vide")
    return normalized


def _require_non_blank(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("la valeur ne doit pas etre vide")
    return normalized


_NormalizedAdapter = Annotated[str, AfterValidator(_normalize_adapter)]
_NonBlankString = Annotated[str, AfterValidator(_require_non_blank)]


class LangGraphSemanticSearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    embed: str | None = None
    dims: int | None = None
    fields: list[str] = Field(default_factory=lambda: ["$"])

    @field_validator("dims")
    @classmethod
    def must_have_positive_dimensions(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("semantic_search.dims doit etre > 0")
        return v

    @field_validator("fields")
    @classmethod
    def must_have_non_empty_fields(cls, v: list[str]) -> list[str]:
        if not v or any(not field.strip() for field in v):
            raise ValueError(
                "semantic_search.fields doit contenir des chemins non vides"
            )
        return v

    @model_validator(mode="after")
    def validate_enabled_search(self) -> "LangGraphSemanticSearchSettings":
        if self.enabled and (not self.embed or self.dims is None):
            raise ValueError(
                "semantic_search.embed et semantic_search.dims sont requis quand la recherche est activee"
            )
        return self


class LangGraphCheckpointerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: _NormalizedAdapter = "none"
    setup: bool = False
    ttl_seconds: int | None = None
    path: _NonBlankString = ".arclith/langgraph-checkpoints.sqlite"
    connection_uri_env: str | None = None
    database: _NonBlankString = "langgraph"
    factory: str | None = None
    options: dict[str, object] = Field(default_factory=dict)

    @field_validator("ttl_seconds")
    @classmethod
    def must_have_positive_ttl(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("ttl_seconds doit etre > 0")
        return v


class LangGraphStoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: _NormalizedAdapter = "none"
    setup: bool = False
    connection_uri_env: str | None = None
    database: _NonBlankString = "langgraph"
    collection: _NonBlankString = "memories"
    factory: str | None = None
    options: dict[str, object] = Field(default_factory=dict)
    namespace_template: str = "{tenant_id}:{user_id}:memories"
    semantic_search: LangGraphSemanticSearchSettings = Field(
        default_factory=LangGraphSemanticSearchSettings
    )

    @field_validator("namespace_template")
    @classmethod
    def must_have_valid_namespace_template(cls, v: str) -> str:
        value = v.strip()
        if not value or any(not part.strip() for part in value.split(":")):
            raise ValueError(
                "namespace_template doit contenir des segments non vides separes par ':'"
            )
        return value


class LangGraphPersistenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    mode: Literal["auto", "embedded", "agent_server"] = "auto"
    checkpointer: LangGraphCheckpointerSettings = Field(
        default_factory=LangGraphCheckpointerSettings
    )
    store: LangGraphStoreSettings = Field(default_factory=LangGraphStoreSettings)


class LangGraphSettings(BaseModel):
    name: str = "agent"
    graph: str = "agent"
    entrypoint: str
    env: str = ".env"
    stream_mode: LangGraphStreamMode | list[LangGraphStreamMode] = "updates"
    persistence: LangGraphPersistenceSettings | None = None
