from __future__ import annotations

import hashlib
import json
import keyword
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


FEATURE_MANIFEST_VERSION = 1
PARAMETERIZED_FEATURE_MANIFEST_VERSION = 2
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class FeatureEntity:
    name: str
    module: str

    @classmethod
    def from_dict(cls, raw: object) -> FeatureEntity:
        data = _mapping(raw, "feature.entity")
        _exact_keys(data, {"name", "module"}, "feature.entity")
        return cls(
            name=_string(data["name"], "feature.entity.name"),
            module=_string(data["module"], "feature.entity.module"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "module": self.module}


@dataclass(frozen=True)
class FeatureBlueprint:
    name: str
    version: int

    @classmethod
    def from_dict(cls, raw: object) -> FeatureBlueprint:
        data = _mapping(raw, "feature.blueprint")
        _exact_keys(data, {"name", "version"}, "feature.blueprint")
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("feature.blueprint.version must be a positive integer")
        return cls(
            name=_string(data["name"], "feature.blueprint.name"),
            version=version,
        )

    def to_dict(self) -> dict[str, str | int]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class FeatureDigests:
    template: str
    parameters: str

    @classmethod
    def from_dict(cls, raw: object) -> FeatureDigests:
        data = _mapping(raw, "feature.digests")
        _exact_keys(data, {"template", "parameters"}, "feature.digests")
        template = _digest(data["template"], "feature.digests.template")
        parameters = _digest(data["parameters"], "feature.digests.parameters")
        return cls(template=template, parameters=parameters)

    def to_dict(self) -> dict[str, str]:
        return {"template": self.template, "parameters": self.parameters}


@dataclass(frozen=True)
class FeatureManifest:
    version: int
    feature: str
    entity: FeatureEntity
    blueprint: FeatureBlueprint
    operations: tuple[str, ...]
    parameters: dict[str, Any] | None = None
    digests: FeatureDigests | None = None

    @classmethod
    def from_dict(cls, raw: object) -> FeatureManifest:
        data = _mapping(raw, "feature manifest")
        if "version" not in data:
            raise ValueError("feature manifest must declare version")
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("feature.version must be an integer")
        common_keys = {"version", "feature", "entity", "blueprint", "operations"}
        if version == FEATURE_MANIFEST_VERSION:
            _exact_keys(data, common_keys, "feature manifest version 1")
            parameters = None
            digests = None
        elif version == PARAMETERIZED_FEATURE_MANIFEST_VERSION:
            _exact_keys(
                data,
                common_keys | {"parameters", "digests"},
                "feature manifest version 2",
            )
            parameters = _json_safe_mapping(data["parameters"], "feature.parameters")
            if not parameters:
                raise ValueError("feature.parameters must not be empty")
            digests = FeatureDigests.from_dict(data["digests"])
            if digests.parameters != parameter_mapping_digest(parameters):
                raise ValueError(
                    "feature.digests.parameters does not match canonical parameters"
                )
        else:
            raise ValueError(
                f"Unsupported feature manifest version {version!r}; "
                f"expected {FEATURE_MANIFEST_VERSION} or "
                f"{PARAMETERIZED_FEATURE_MANIFEST_VERSION}"
            )
        raw_operations = data["operations"]
        if not isinstance(raw_operations, list) or not raw_operations:
            raise ValueError("feature.operations must be a non-empty list")
        operations = tuple(
            _string(operation, "feature.operations[]") for operation in raw_operations
        )
        if len(operations) != len(set(operations)):
            raise ValueError("feature.operations must not contain duplicates")
        return cls(
            version=version,
            feature=_identifier(data["feature"], "feature.feature"),
            entity=FeatureEntity.from_dict(data["entity"]),
            blueprint=FeatureBlueprint.from_dict(data["blueprint"]),
            operations=operations,
            parameters=parameters,
            digests=digests,
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "version": self.version,
            "feature": self.feature,
            "entity": self.entity.to_dict(),
            "blueprint": self.blueprint.to_dict(),
        }
        if self.version == PARAMETERIZED_FEATURE_MANIFEST_VERSION:
            if self.parameters is None or self.digests is None:
                raise ValueError(
                    "Feature manifest version 2 requires parameters and digests"
                )
            data["parameters"] = _json_safe_mapping(
                self.parameters, "feature.parameters"
            )
            data["digests"] = self.digests.to_dict()
        elif self.parameters is not None or self.digests is not None:
            raise ValueError(
                "Feature manifest version 1 must not contain parameters or digests"
            )
        data["operations"] = list(self.operations)
        return data


def load_feature_manifest(path: Path) -> FeatureManifest:
    if not path.is_file():
        raise ValueError(f"Feature manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in feature manifest {path}: {exc}") from exc
    return FeatureManifest.from_dict(raw)


def render_feature_manifest(manifest: FeatureManifest) -> str:
    validated = FeatureManifest.from_dict(manifest.to_dict())
    return yaml.safe_dump(
        validated.to_dict(),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def save_feature_manifest(manifest: FeatureManifest, path: Path) -> None:
    rendered = render_feature_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parameter_mapping_digest(parameters: dict[str, Any]) -> str:
    """Hash a validated JSON/YAML-safe parameter mapping deterministically."""

    validated = _json_safe_mapping(parameters, "feature.parameters")
    encoded = json.dumps(
        validated,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _mapping(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must be a mapping with string keys")
    return raw


def _exact_keys(data: dict[str, Any], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(expected))}")


def _string(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return raw


def _identifier(raw: object, label: str) -> str:
    value = _string(raw, label)
    if not value.isidentifier() or value.startswith("_") or keyword.iskeyword(value):
        raise ValueError(f"{label} must be a public Python identifier")
    return value


def _digest(raw: object, label: str) -> str:
    value = _string(raw, label)
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label} must be a sha256 digest")
    return value


def _json_safe_mapping(raw: object, label: str) -> dict[str, Any]:
    data = _mapping(raw, label)
    return {
        key: _json_safe_value(value, f"{label}.{key}") for key, value in data.items()
    }


def _json_safe_value(raw: object, label: str) -> Any:
    if raw is None or isinstance(raw, (str, bool, int)):
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise ValueError(f"{label} must contain only finite JSON numbers")
        return raw
    if isinstance(raw, list):
        return [_json_safe_value(item, f"{label}[]") for item in raw]
    if isinstance(raw, dict) and all(isinstance(key, str) for key in raw):
        return {
            key: _json_safe_value(value, f"{label}.{key}") for key, value in raw.items()
        }
    raise ValueError(f"{label} must contain only JSON/YAML-safe values")
