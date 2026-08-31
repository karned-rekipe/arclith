from __future__ import annotations

from typing import Any

from arclith_cli.capability_models import (  # noqa: F401
    AdapterProfileSpec,
    AdapterSpec,
    CapabilitySpec,
    FileTemplateSpec,
    LayerKind,
    ParameterKind,
    ParameterSpec,
    SecretMappingSpec,
)
from arclith_cli.catalogs.ai import (
    AGENT_CAPABILITY,
    AGENT_PERSISTENCE_CAPABILITY,
    LLM_CAPABILITY,
)
from arclith_cli.catalogs.core import (
    CACHE_CAPABILITY,
    LOGGER_CAPABILITY,
    SECRETS_CAPABILITY,
)
from arclith_cli.catalogs.observability import OBSERVABILITY_CAPABILITY
from arclith_cli.catalogs.persistence import REPOSITORY_CAPABILITY, STORAGE_CAPABILITY
from arclith_cli.catalogs.security import (
    AUTH_CAPABILITY,
    LICENSE_CAPABILITY,
    TENANT_CAPABILITY,
)
from arclith_cli.catalogs.transports import (
    API_CAPABILITY,
    COMMAND_BUS_CAPABILITY,
    HTTP_CAPABILITY,
    MCP_CAPABILITY,
    PROBE_CAPABILITY,
    RUNTIME_CAPABILITY,
)

CAPABILITY_CATALOG = (
    REPOSITORY_CAPABILITY,
    STORAGE_CAPABILITY,
    CACHE_CAPABILITY,
    LOGGER_CAPABILITY,
    SECRETS_CAPABILITY,
    API_CAPABILITY,
    MCP_CAPABILITY,
    PROBE_CAPABILITY,
    HTTP_CAPABILITY,
    COMMAND_BUS_CAPABILITY,
    RUNTIME_CAPABILITY,
    AUTH_CAPABILITY,
    TENANT_CAPABILITY,
    LICENSE_CAPABILITY,
    LLM_CAPABILITY,
    AGENT_CAPABILITY,
    AGENT_PERSISTENCE_CAPABILITY,
    OBSERVABILITY_CAPABILITY,
)


def get_capability(name: str) -> CapabilitySpec | None:
    normalized = name.strip().lower()
    for capability in CAPABILITY_CATALOG:
        if capability.name == normalized:
            return capability
    return None


def capability_names() -> tuple[str, ...]:
    return tuple(capability.name for capability in CAPABILITY_CATALOG)


def repository_adapter_names() -> tuple[str, ...]:
    return REPOSITORY_CAPABILITY.adapter_names()


def capability_catalog_as_dict() -> list[dict[str, Any]]:
    return [capability.to_dict() for capability in CAPABILITY_CATALOG]
