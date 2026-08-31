from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LangSmithTracingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: Literal["langsmith", "otel", "hybrid"] = "otel"
    sampling_rate: float = 1.0

    @field_validator("sampling_rate")
    @classmethod
    def must_be_valid_sampling_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("sampling_rate doit etre compris entre 0.0 et 1.0")
        return v


class LangSmithInstrumentationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    langgraph: bool = True
    pydantic_ai: bool = True
    fastapi: bool = False
    fastmcp: bool = True
    command_bus: bool = True


class LangSmithCaptureSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: bool = False
    outputs: bool = False
    metadata: bool = True
    model_content: bool = False
    binary_content: bool = False
    model_request_parameters: bool = False


class LangSmithPropagationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    langsmith_headers: bool = True
    traceparent: bool = True
    baggage_allowlist: list[str] = Field(default_factory=list)

    @field_validator("baggage_allowlist")
    @classmethod
    def must_not_contain_duplicate_baggage_keys(cls, v: list[str]) -> list[str]:
        normalized = [item.strip() for item in v if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("baggage_allowlist ne doit pas contenir de doublons")
        return normalized


class LangSmithLifecycleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flush_timeout_seconds: float = 5.0

    @field_validator("flush_timeout_seconds")
    @classmethod
    def must_be_positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("flush_timeout_seconds doit etre > 0")
        return v


class LangSmithDiagnosticsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class LangSmithSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    endpoint: str = "https://api.smith.langchain.com"
    api_key_env: str = "LANGSMITH_API_KEY"
    workspace_id_env: str = "LANGSMITH_WORKSPACE_ID"
    tracing: LangSmithTracingSettings = Field(default_factory=LangSmithTracingSettings)
    instrumentation: LangSmithInstrumentationSettings = Field(
        default_factory=LangSmithInstrumentationSettings
    )
    capture: LangSmithCaptureSettings = Field(default_factory=LangSmithCaptureSettings)
    propagation: LangSmithPropagationSettings = Field(
        default_factory=LangSmithPropagationSettings
    )
    tags: list[str] = Field(default_factory=lambda: ["arclith"])
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    lifecycle: LangSmithLifecycleSettings = Field(
        default_factory=LangSmithLifecycleSettings
    )
    diagnostics: LangSmithDiagnosticsSettings = Field(
        default_factory=LangSmithDiagnosticsSettings
    )
    failure_mode: Literal["log-and-continue", "raise"] = "log-and-continue"
    studio: Literal["langgraph"] = "langgraph"
    langgraph_api_min_version: str = "0.11.0"

    @field_validator("tracing", mode="before")
    @classmethod
    def migrate_legacy_tracing_flag(cls, v: object) -> object:
        if isinstance(v, bool):
            return {"enabled": v}
        return v

    @field_validator("project", "endpoint", "api_key_env", "workspace_id_env")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("la valeur ne doit pas etre vide")
        return value
