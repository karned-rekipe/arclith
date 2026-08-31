from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ParameterKind = Literal["string", "boolean"]
LayerKind = Literal["inbound", "outbound", "bidirectional", "runtime"]


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    prompt: str
    default: str | bool | None = None
    default_from_project_name: bool = False
    secret: bool = False
    required: bool = False
    choices: tuple[str, ...] = ()
    csv_choices: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "prompt": self.prompt,
            "default": self.default,
            "default_from_project_name": self.default_from_project_name,
            "secret": self.secret,
            "required": self.required,
            "choices": list(self.choices),
            "csv_choices": self.csv_choices,
        }


@dataclass(frozen=True)
class FileTemplateSpec:
    path: str
    template: str
    preserve_existing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "preserve_existing": self.preserve_existing,
        }


@dataclass(frozen=True)
class SecretMappingSpec:
    field_path: str
    secret_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "secret_key": self.secret_key,
        }


@dataclass(frozen=True)
class AdapterProfileSpec:
    name: str
    parameters: tuple[tuple[str, str | bool], ...]

    def values(self) -> dict[str, str | bool]:
        return dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    capability: str
    layer: LayerKind
    description: str
    config_path: str | None = None
    config_template: str = ""
    merge_config_templates: tuple[FileTemplateSpec, ...] = ()
    env_path: str | None = None
    env_template: str = ""
    file_templates: tuple[FileTemplateSpec, ...] = ()
    secret_mappings: tuple[SecretMappingSpec, ...] = ()
    secret_resolver: str | None = None
    secret_config_template: str = ""
    gitignore_entries: tuple[str, ...] = ()
    parameters: tuple[ParameterSpec, ...] = ()
    profiles: tuple[AdapterProfileSpec, ...] = ()
    dependency_extra: str | None = None
    entity_scoped: bool = True

    def has_config(self) -> bool:
        return self.config_path is not None and bool(self.config_template)

    def has_env(self) -> bool:
        return self.env_path is not None and bool(self.env_template)

    def has_file_templates(self) -> bool:
        return bool(self.file_templates)

    def has_secret_mappings(self) -> bool:
        return bool(self.secret_mappings)

    def has_secret_config(self) -> bool:
        return bool(self.secret_config_template)

    def get_profile(self, name: str) -> AdapterProfileSpec | None:
        normalized = name.strip().lower()
        return next(
            (profile for profile in self.profiles if profile.name == normalized),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "layer": self.layer,
            "description": self.description,
            "config_path": self.config_path,
            "merge_config_templates": [
                file_template.to_dict() for file_template in self.merge_config_templates
            ],
            "env_path": self.env_path,
            "file_templates": [
                file_template.to_dict() for file_template in self.file_templates
            ],
            "secret_mappings": [
                secret_mapping.to_dict() for secret_mapping in self.secret_mappings
            ],
            "secret_resolver": self.secret_resolver,
            "secret_config_template": bool(self.secret_config_template),
            "gitignore_entries": list(self.gitignore_entries),
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "profiles": [profile.to_dict() for profile in self.profiles],
            "dependency_extra": self.dependency_extra,
            "entity_scoped": self.entity_scoped,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    layer: LayerKind
    description: str
    activation_config_key: str | None
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


__all__ = [
    "AdapterProfileSpec",
    "AdapterSpec",
    "CapabilitySpec",
    "FileTemplateSpec",
    "LayerKind",
    "ParameterKind",
    "ParameterSpec",
    "SecretMappingSpec",
]
