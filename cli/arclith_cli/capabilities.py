from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ParameterKind = Literal["string", "boolean"]
LayerKind = Literal["inbound", "outbound"]


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    prompt: str
    default: str | bool | None = None
    default_from_project_name: bool = False
    secret: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "prompt": self.prompt,
            "default": self.default,
            "default_from_project_name": self.default_from_project_name,
            "secret": self.secret,
        }


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    capability: str
    layer: LayerKind
    description: str
    config_path: str | None = None
    config_template: str = ""
    parameters: tuple[ParameterSpec, ...] = ()
    entity_scoped: bool = True

    def has_config(self) -> bool:
        return self.config_path is not None and bool(self.config_template)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "layer": self.layer,
            "description": self.description,
            "config_path": self.config_path,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "entity_scoped": self.entity_scoped,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    layer: LayerKind
    description: str
    activation_config_key: str
    adapters: tuple[AdapterSpec, ...]

    def adapter_names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self.adapters)

    def get_adapter(self, name: str) -> AdapterSpec | None:
        normalized = name.strip().lower()
        for adapter in self.adapters:
            if adapter.name == normalized:
                return adapter
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "description": self.description,
            "activation_config_key": self.activation_config_key,
            "adapters": [adapter.to_dict() for adapter in self.adapters],
        }


REPOSITORY_CAPABILITY = CapabilitySpec(
    name="repository",
    layer="outbound",
    description="Persistance des entites metier derriere un port repository.",
    activation_config_key="repository",
    adapters=(
        AdapterSpec(
            name="memory",
            capability="repository",
            layer="outbound",
            description="Stockage volatile en memoire pour dev, tests et smoke locaux.",
        ),
        AdapterSpec(
            name="mongodb",
            capability="repository",
            layer="outbound",
            description="Repository MongoDB async avec configuration single-tenant ou multitenant.",
            config_path="config/adapters/outbound/mongodb.yaml",
            config_template="""\
multitenant: {multitenant}   # true = URI + db_name resolus par requete via JWT -> Vault
db_name: {db_name}   # uri -> secrets.yaml ou Vault (fallback single-tenant)
""",
            parameters=(
                ParameterSpec(
                    name="db_name",
                    kind="string",
                    prompt="db_name",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="multitenant",
                    default=False,
                ),
            ),
        ),
        AdapterSpec(
            name="duckdb",
            capability="repository",
            layer="outbound",
            description="Repository fichier local pour SQL analytique et demos sans serveur.",
            config_path="config/adapters/outbound/duckdb.yaml",
            config_template="""\
multitenant: false
path: {path}
""",
            parameters=(
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="path",
                    default="data/",
                ),
            ),
        ),
    ),
)

CAPABILITY_CATALOG = (REPOSITORY_CAPABILITY,)


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
