from __future__ import annotations

import keyword
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


FEATURE_MANIFEST_VERSION = 1


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
class FeatureManifest:
    version: int
    feature: str
    entity: FeatureEntity
    blueprint: FeatureBlueprint
    operations: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: object) -> FeatureManifest:
        data = _mapping(raw, "feature manifest")
        _exact_keys(
            data,
            {"version", "feature", "entity", "blueprint", "operations"},
            "feature manifest",
        )
        version = data["version"]
        if version != FEATURE_MANIFEST_VERSION:
            raise ValueError(
                f"Unsupported feature manifest version {version!r}; "
                f"expected {FEATURE_MANIFEST_VERSION}"
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
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "feature": self.feature,
            "entity": self.entity.to_dict(),
            "blueprint": self.blueprint.to_dict(),
            "operations": list(self.operations),
        }


def load_feature_manifest(path: Path) -> FeatureManifest:
    if not path.is_file():
        raise ValueError(f"Feature manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
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
