"""Portable sequential workflow definition; executable business steps stay local."""

import keyword
from dataclasses import dataclass
from pathlib import Path

import yaml

from arclith_cli.feature_manifest import parameter_mapping_digest

WORKFLOW_OPERATIONS = ("start", "get_status", "cancel", "resume", "get_result")


def require_workflow_runtime() -> None:
    try:
        from arclith.application.services.workflow_runner import (
            SequentialWorkflowRunner,
        )
        from arclith.domain.models.workflow import WorkflowDefinition
    except ImportError as exc:
        raise ValueError(
            "Workflow requires a compatible Arclith framework and CLI containing the workflow contracts; install both from the same compatible release or source checkout"
        ) from exc
    if SequentialWorkflowRunner is None or WorkflowDefinition is None:
        raise ValueError("Workflow runtime is unavailable")


@dataclass(frozen=True)
class WorkflowSpec:
    context: str
    result: str
    steps: tuple[tuple[str, int], ...]
    definition_version: int = 1
    version: int = 1

    @classmethod
    def from_dict(cls, raw: object) -> "WorkflowSpec":
        require_workflow_runtime()
        from arclith.domain.models.workflow import WorkflowDefinition

        required = {"version", "context", "result", "steps"}
        if (
            not isinstance(raw, dict)
            or not required <= raw.keys()
            or set(raw) - required - {"definition_version"}
        ):
            raise ValueError(
                "Workflow spec requires version, context, result, steps and optional definition_version"
            )
        if type(raw["version"]) is not int or raw["version"] != 1:
            raise ValueError("Workflow spec.version must be integer 1")
        definition = WorkflowDefinition(
            name="workflow",
            version=raw.get("definition_version", 1),
            context=raw["context"],
            result=raw["result"],
            steps=raw["steps"],
        )
        for name in (
            definition.context,
            definition.result,
            *(step.name for step in definition.steps),
        ):
            if keyword.iskeyword(name) or name in {
                "BaseModel",
                "ConfigDict",
                "Field",
                "WorkflowDefinition",
                "WorkflowStepDefinition",
            }:
                raise ValueError(
                    "Workflow names must be public Python identifiers without reserved names"
                )
        return cls(
            definition.context,
            definition.result,
            tuple((step.name, step.max_attempts) for step in definition.steps),
            definition.version,
        )

    @classmethod
    def from_parameters(cls, raw: object) -> "WorkflowSpec":
        if not isinstance(raw, dict) or "version" in raw:
            raise ValueError("Workflow parameters must be a mapping without version")
        return cls.from_dict({"version": 1, **raw})

    def to_parameters(self) -> dict[str, object]:
        return {
            "context": self.context,
            "result": self.result,
            "definition_version": self.definition_version,
            "steps": [
                {"name": name, "max_attempts": attempts}
                for name, attempts in self.steps
            ],
        }

    def digest(self) -> str:
        return parameter_mapping_digest(self.to_parameters())


def load_workflow_spec(path: Path) -> WorkflowSpec:
    if not path.is_file():
        raise ValueError(f"Workflow spec not found: {path}")
    if path.stat().st_size > 65_536:
        raise ValueError("Workflow spec exceeds 64 KiB")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("Unable to read workflow spec as UTF-8 YAML") from exc
    return WorkflowSpec.from_dict(raw)
