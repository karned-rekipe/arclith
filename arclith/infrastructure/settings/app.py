from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from arclith.infrastructure.settings._base import SettingsModel

from arclith.infrastructure.settings.langgraph import LangGraphSettings
from arclith.infrastructure.settings.langsmith import LangSmithSettings
from arclith.infrastructure.settings.llm import LMSettings
from arclith.infrastructure.settings.observability import (
    ObservabilityAdapter,
    ObservabilitySettings,
)
from arclith.infrastructure.settings.opentelemetry import OpenTelemetrySettings
from arclith.infrastructure.settings.repositories import (
    DuckDBSettings,
    MariaDBSettings,
    MongoDBSettings,
    PostgreSQLSettings,
)
from arclith.infrastructure.settings.storage import StorageSettings

_REPOSITORY_CONFIG_SECTIONS: dict[str, str] = {
    "mongodb": "mongodb",
    "duckdb": "duckdb",
    "mariadb": "mariadb",
    "postgresql": "postgresql",
}
_LOGGER_ADAPTERS = {"console"}
_OBSERVABILITY_CONFIG_SECTIONS: dict[ObservabilityAdapter, str] = {
    "langsmith": "langsmith",
    "opentelemetry": "opentelemetry",
}


class SoftDeleteSettings(SettingsModel):
    retention_days: float | None = None

    @field_validator("retention_days")
    @classmethod
    def must_be_positive(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("retention_days doit être >= 0")
        return v


class AdaptersSettings(SettingsModel):
    logger: str = "console"
    repository: str = "memory"
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    mongodb: MongoDBSettings | None = None
    duckdb: DuckDBSettings | None = None
    mariadb: MariaDBSettings | None = None
    postgresql: PostgreSQLSettings | None = None
    storage: StorageSettings | None = None
    lm: LMSettings | None = None
    langsmith: LangSmithSettings | None = None
    opentelemetry: OpenTelemetrySettings | None = None

    @property
    def multitenant(self) -> bool:
        settings = {
            "mongodb": self.mongodb,
            "duckdb": self.duckdb,
            "mariadb": self.mariadb,
            "postgresql": self.postgresql,
        }.get(self.repository)
        return bool(settings and settings.multitenant)

    @field_validator("logger")
    @classmethod
    def must_be_supported_logger_adapter(cls, v: str) -> str:
        if v not in _LOGGER_ADAPTERS:
            supported = ", ".join(sorted(_LOGGER_ADAPTERS))
            raise ValueError(
                f"logger={v} non supporte. Adapters logger supportes: {supported}"
            )
        return v

    @model_validator(mode="after")
    def validate_repository_config(self) -> "AdaptersSettings":
        repository_section = _REPOSITORY_CONFIG_SECTIONS.get(self.repository)
        if repository_section is not None and getattr(self, repository_section) is None:
            raise ValueError(
                f"repository={self.repository} mais aucune section [adapters.{repository_section}] dans config.yaml"
            )

        for observability_adapter in self.observability.enabled:
            observability_section = _OBSERVABILITY_CONFIG_SECTIONS[
                observability_adapter
            ]
            if getattr(self, observability_section) is None:
                raise ValueError(
                    f"observability.enabled contient {observability_adapter} mais aucune section "
                    f"[adapters.{observability_section}] dans config.yaml"
                )
        self._validate_observability_composition()
        return self

    def _validate_observability_composition(self) -> None:
        self._validate_langsmith_otel_mode()
        self._validate_langsmith_trace_signal()

    def _validate_langsmith_otel_mode(self) -> None:
        if (
            self.observability.is_enabled("langsmith")
            and self.observability.is_enabled("opentelemetry")
            and self.langsmith is not None
            and self.langsmith.tracing.mode != "otel"
        ):
            raise ValueError(
                "LangSmith + OpenTelemetry requiert tracing.mode=otel afin de "
                "partager un seul arbre de spans sans doublons"
            )

    def _validate_langsmith_trace_signal(self) -> None:
        if (
            self.observability.is_enabled("langsmith")
            and self.observability.is_enabled("opentelemetry")
            and self.langsmith is not None
            and self.langsmith.tracing.enabled
            and self.opentelemetry is not None
            and not self.opentelemetry.signals.traces.enabled
        ):
            raise ValueError(
                "LangSmith tracing.mode=otel requiert signals.traces.enabled=true "
                "dans la configuration OpenTelemetry partagee"
            )


class ApiSettings(SettingsModel):
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    reload: bool = True


class McpSettings(SettingsModel):
    host: str = "127.0.0.1"
    port: int = 8001


class ProbeSettings(SettingsModel):
    host: str = "0.0.0.0"  # nosec B104
    port: int = 9000
    enabled: bool = True


class KeycloakSettings(SettingsModel):
    url: str
    realm: str
    audience: str | None = None
    client_id: str | None = (
        None  # Client OAuth2 pour Swagger UI (doit être public/PKCE)
    )


class TenantSettings(SettingsModel):
    vault_addr: str = "http://127.0.0.1:8200"
    vault_mount: str = "kv"
    vault_path_prefix: str
    tenant_claim: str = "sub"


class LicenseSettings(SettingsModel):
    role: str = "rekipe:licensed"


class CacheSettings(SettingsModel):
    backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:6379"
    jwks_ttl: int = 3600
    tenant_uri_ttl: int = 300


CommandBusAdapter = Literal["rabbitmq"]


class RabbitMQCommandBusSettings(SettingsModel):
    url: str = "amqp://guest:guest@127.0.0.1:5672/"
    exchange: str = "arclith.commands"
    exchange_type: Literal["direct", "topic"] = "topic"
    queue: str = "arclith.commands"
    routing_key: str = "commands"
    prefetch: int = 10
    consumer_name: str = "arclith-command-worker"
    concurrency: int = 1
    publisher_confirms: bool = True
    durable: bool = True
    retry_enabled: bool = True
    retry_requeue: bool = False
    dead_letter_exchange: str = "arclith.commands.dlx"
    dead_letter_routing_key: str = "commands.dead"

    @field_validator(
        "url",
        "exchange",
        "queue",
        "routing_key",
        "consumer_name",
        "dead_letter_exchange",
        "dead_letter_routing_key",
    )
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rabbitmq command-bus fields ne doivent pas etre vides")
        return v

    @field_validator("prefetch", "concurrency")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                "rabbitmq command-bus prefetch/concurrency doivent etre > 0"
            )
        return v


class CommandBusSettings(SettingsModel):
    enabled: list[CommandBusAdapter] = Field(default_factory=list)
    rabbitmq: RabbitMQCommandBusSettings = RabbitMQCommandBusSettings()

    @field_validator("enabled")
    @classmethod
    def must_not_contain_duplicates(
        cls, v: list[CommandBusAdapter]
    ) -> list[CommandBusAdapter]:
        if len(v) != len(set(v)):
            raise ValueError("command_bus.enabled ne doit pas contenir de doublons")
        return v

    def is_enabled(self, adapter: CommandBusAdapter) -> bool:
        return adapter in self.enabled


class IdempotencySettings(SettingsModel):
    enabled: bool = True
    ttl_seconds: int = 86400  # 24 hours
    required: bool = False  # If True, reject POST without Idempotency-Key


class ETagSettings(SettingsModel):
    enabled: bool = True


class CacheControlSettings(SettingsModel):
    get_single_max_age: int = 300  # 5 minutes
    get_list_max_age: int = 60  # 1 minute

    @field_validator("get_single_max_age", "get_list_max_age")
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cache_control max-age doit etre >= 0")
        return v


class HttpSettings(SettingsModel):
    idempotency: IdempotencySettings = IdempotencySettings()
    etag: ETagSettings = ETagSettings()
    cache_control: CacheControlSettings = CacheControlSettings()


class AppSettings(SettingsModel):
    name: str = "arclith-service"
    version: str = "0.0.0"
    description: str = "API service built with arclith framework"


class AppConfig(SettingsModel):
    app: AppSettings = AppSettings()
    adapters: AdaptersSettings = AdaptersSettings()
    soft_delete: SoftDeleteSettings = SoftDeleteSettings()
    api: ApiSettings = ApiSettings()
    mcp: McpSettings = McpSettings()
    langgraph: LangGraphSettings | None = None
    probe: ProbeSettings = ProbeSettings()
    http: HttpSettings = HttpSettings()
    keycloak: KeycloakSettings | None = None
    tenant: TenantSettings | None = None
    license: LicenseSettings | None = None
    cache: CacheSettings = CacheSettings()
    command_bus: CommandBusSettings = CommandBusSettings()
