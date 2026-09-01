from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

RECIPE_FILENAME = "arclith.recipe.yaml"
RECIPE_SCHEMA_VERSION = 1
REDACTED = "<redacted>"
EXTERNAL_PATH = "<external-path>"


class RecipeError(ValueError):
    """Raised when a CLI recipe is missing, invalid, or cannot be replayed."""


@dataclass(frozen=True)
class RecipeProject:
    name: str
    package: str

    @classmethod
    def from_dict(cls, raw: Any) -> RecipeProject:
        data = _require_mapping(raw, "project")
        return cls(
            name=_require_string(data.get("name"), "project.name"),
            package=_require_string(data.get("package"), "project.package"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "package": self.package}


@dataclass(frozen=True)
class RecipeSecretRef:
    field_path: str
    source: str
    key: str
    value: str = REDACTED

    @classmethod
    def from_dict(cls, raw: Any, *, index: int) -> RecipeSecretRef:
        data = _require_mapping(raw, f"steps[].secrets[{index}]")
        value = _require_string(data.get("value"), "secret.value")
        if value != REDACTED:
            raise RecipeError("A recipe secret reference must contain '<redacted>'.")
        return cls(
            field_path=_require_string(data.get("field_path"), "secret.field_path"),
            source=_require_string(data.get("source"), "secret.source"),
            key=_require_string(data.get("key"), "secret.key"),
            value=value,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "source": self.source,
            "key": self.key,
            "value": self.value,
        }


@dataclass(frozen=True)
class RecipeFileChange:
    path: str
    action: str

    @classmethod
    def from_dict(cls, raw: Any, *, index: int) -> RecipeFileChange:
        data = _require_mapping(raw, f"result.generated_files[{index}]")
        path = _require_relative_path(data.get("path"), "generated file path")
        action = _require_string(data.get("action"), "generated file action")
        if action not in {"created", "updated"}:
            raise RecipeError(
                f"Unsupported generated file action {action!r}; expected created or updated."
            )
        return cls(path=path, action=action)

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "action": self.action}


@dataclass(frozen=True)
class RecipeResult:
    generated_files: tuple[RecipeFileChange, ...] = ()

    @classmethod
    def from_dict(cls, raw: Any) -> RecipeResult:
        data = _require_mapping(raw, "step.result")
        files = data.get("generated_files", [])
        if not isinstance(files, list):
            raise RecipeError("step.result.generated_files must be a list.")
        return cls(
            generated_files=tuple(
                RecipeFileChange.from_dict(item, index=index)
                for index, item in enumerate(files)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {"generated_files": [item.to_dict() for item in self.generated_files]}


@dataclass(frozen=True)
class RecipeStep:
    id: str
    at: str
    cli_version: str
    command: str
    status: str
    args: dict[str, Any]
    secrets: tuple[RecipeSecretRef, ...] = ()
    result: RecipeResult = field(default_factory=RecipeResult)

    @classmethod
    def from_dict(cls, raw: Any, *, index: int) -> RecipeStep:
        data = _require_mapping(raw, f"steps[{index}]")
        step_id = _require_string(data.get("id"), f"steps[{index}].id")
        if not re.fullmatch(r"\d{4}", step_id):
            raise RecipeError(
                f"Invalid recipe step id {step_id!r}; expected four digits."
            )
        status = _require_string(data.get("status"), f"steps[{index}].status")
        if status != "success":
            raise RecipeError(
                f"Unsupported recipe step status {status!r}; only successful steps are replayable."
            )
        at = _require_aware_timestamp(data.get("at"), f"steps[{index}].at")
        args = _require_mapping(data.get("args", {}), f"steps[{index}].args")
        secrets_raw = data.get("secrets", [])
        if not isinstance(secrets_raw, list):
            raise RecipeError(f"steps[{index}].secrets must be a list.")
        return cls(
            id=step_id,
            at=at,
            cli_version=_require_string(
                data.get("cli_version"), f"steps[{index}].cli_version"
            ),
            command=_require_string(data.get("command"), f"steps[{index}].command"),
            status=status,
            args=dict(args),
            secrets=tuple(
                RecipeSecretRef.from_dict(item, index=secret_index)
                for secret_index, item in enumerate(secrets_raw)
            ),
            result=RecipeResult.from_dict(data.get("result", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "at": self.at,
            "cli_version": self.cli_version,
            "command": self.command,
            "status": self.status,
            "args": self.args,
        }
        if self.secrets:
            data["secrets"] = [secret.to_dict() for secret in self.secrets]
        data["result"] = self.result.to_dict()
        return data


@dataclass(frozen=True)
class Recipe:
    version: int
    project: RecipeProject
    created_at: str
    updated_at: str
    steps: tuple[RecipeStep, ...] = ()

    @classmethod
    def from_dict(cls, raw: Any) -> Recipe:
        data = _require_mapping(raw, "recipe")
        version = data.get("version")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != RECIPE_SCHEMA_VERSION
        ):
            raise RecipeError(
                f"Unsupported recipe schema version {version!r}; "
                f"this CLI supports version {RECIPE_SCHEMA_VERSION}."
            )
        steps_raw = data.get("steps", [])
        if not isinstance(steps_raw, list):
            raise RecipeError("recipe.steps must be a list.")
        steps = tuple(
            RecipeStep.from_dict(item, index=index)
            for index, item in enumerate(steps_raw)
        )
        ids = [step.id for step in steps]
        if len(ids) != len(set(ids)):
            raise RecipeError("Recipe step ids must be unique.")
        if ids != sorted(ids):
            raise RecipeError("Recipe steps must be ordered by id.")
        return cls(
            version=version,
            project=RecipeProject.from_dict(data.get("project")),
            created_at=_require_aware_timestamp(data.get("created_at"), "created_at"),
            updated_at=_require_aware_timestamp(data.get("updated_at"), "updated_at"),
            steps=steps,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [step.to_dict() for step in self.steps],
        }


def load_recipe(path: Path) -> Recipe:
    """Load and validate a versioned CLI recipe."""
    if not path.is_file():
        raise RecipeError(f"Recipe file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RecipeError(f"Unable to read recipe {path}: {exc}") from exc
    if raw is None:
        raise RecipeError(f"Recipe file is empty: {path}")
    return Recipe.from_dict(raw)


def save_recipe(recipe: Recipe, path: Path) -> None:
    """Validate and atomically write a recipe in its project directory."""
    validated = Recipe.from_dict(recipe.to_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(
        validated.to_dict(),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
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


def _require_mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecipeError(f"{label} must be a mapping.")
    if not all(isinstance(key, str) for key in raw):
        raise RecipeError(f"{label} keys must be strings.")
    return raw


def _require_string(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise RecipeError(f"{label} must be a non-empty string.")
    return raw


def _require_aware_timestamp(raw: Any, label: str) -> str:
    value = _require_string(raw, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RecipeError(f"{label} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecipeError(f"{label} must include a timezone offset.")
    return value


def _require_relative_path(raw: Any, label: str) -> str:
    value = _require_string(raw, label)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RecipeError(f"{label} must be relative to the project root: {value}")
    return path.as_posix()
