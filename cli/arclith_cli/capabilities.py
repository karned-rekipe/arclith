from __future__ import annotations

from typing import Any

from arclith_cli.capability_models import (
    AdapterFacets,
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
    EMBEDDING_CAPABILITY,
    LLM_CAPABILITY,
)
from arclith_cli.catalogs.core import (
    CACHE_CAPABILITY,
    LOGGER_CAPABILITY,
    SECRETS_CAPABILITY,
)
from arclith_cli.catalogs.observability import OBSERVABILITY_CAPABILITY
from arclith_cli.catalogs.persistence import (
    REPOSITORY_CAPABILITY,
    STORAGE_CAPABILITY,
    VECTOR_STORE_CAPABILITY,
)
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

__all__ = [
    "AGENT_CAPABILITY",
    "AGENT_PERSISTENCE_CAPABILITY",
    "API_CAPABILITY",
    "AUTH_CAPABILITY",
    "AdapterFacets",
    "AdapterProfileSpec",
    "AdapterSpec",
    "CACHE_CAPABILITY",
    "CAPABILITY_CATALOG",
    "COMMAND_BUS_CAPABILITY",
    "CapabilitySpec",
    "EMBEDDING_CAPABILITY",
    "FileTemplateSpec",
    "HTTP_CAPABILITY",
    "LICENSE_CAPABILITY",
    "LLM_CAPABILITY",
    "LOGGER_CAPABILITY",
    "LayerKind",
    "MCP_CAPABILITY",
    "OBSERVABILITY_CAPABILITY",
    "PROBE_CAPABILITY",
    "ParameterKind",
    "ParameterSpec",
    "REPOSITORY_CAPABILITY",
    "RUNTIME_CAPABILITY",
    "SECRETS_CAPABILITY",
    "STORAGE_CAPABILITY",
    "SecretMappingSpec",
    "TENANT_CAPABILITY",
    "VECTOR_STORE_CAPABILITY",
    "capability_catalog_as_dict",
    "capability_names",
    "get_capability",
    "repository_adapter_names",
]

CAPABILITY_CATALOG = (
    REPOSITORY_CAPABILITY,
    STORAGE_CAPABILITY,
    VECTOR_STORE_CAPABILITY,
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
    EMBEDDING_CAPABILITY,
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
