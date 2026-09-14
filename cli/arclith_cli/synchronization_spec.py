"""Canonical synchronization parameters, using the framework's policy contract."""

import keyword
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ValidationError

from arclith_cli.feature_manifest import parameter_mapping_digest

if TYPE_CHECKING:
    from arclith.domain.models.synchronization import SyncDefinition

SYNC_OPERATIONS = ("start_sync", "get_sync_status", "cancel_sync", "get_sync_report")
_REQUIRED = {
    "version",
    "direction",
    "modes",
    "external_key",
    "page_size",
    "conflict_policy",
    "missing_policy",
    "execution",
}
_OPTIONAL = {"source_version", "max_full_items", "max_pages"}


def require_synchronization_runtime() -> None:
    try:
        from arclith.application.services.synchronization import SyncJobHandler
        from arclith.domain.models.job import JobProgress
        from arclith.domain.ports.outbound.job_runner import JobContext
    except ImportError:
        raise ValueError(
            "Synchronization requires an Arclith build containing job #224 and synchronization #225; "
            "install compatible framework and CLI sources together before generation/replay."
        ) from None
    if (
        "completed" not in JobProgress.model_fields
        or not hasattr(JobContext, "job_id")
        or SyncJobHandler is None
    ):
        raise ValueError(
            "Synchronization requires the Job identity and counter-progress contracts"
        )


@dataclass(frozen=True)
class SynchronizationSpec:
    definition: "SyncDefinition"

    @classmethod
    def from_dict(cls, raw: object) -> "SynchronizationSpec":
        require_synchronization_runtime()
        from arclith.domain.models.synchronization import SyncDefinition

        if (
            not isinstance(raw, dict)
            or not _REQUIRED <= raw.keys()
            or raw.keys() - _REQUIRED - _OPTIONAL
        ):
            raise ValueError(
                "Synchronization spec requires version, direction, modes, external_key, page_size, conflict_policy, missing_policy, execution"
            )
        if type(raw["version"]) is not int or raw["version"] != 1:
            raise ValueError("Synchronization spec.version must be integer 1")
        external_key = raw["external_key"]
        if (
            not isinstance(external_key, str)
            or keyword.iskeyword(external_key)
            or hasattr(BaseModel, external_key)
            or external_key.startswith("model_")
        ):
            raise ValueError(
                "Synchronization external_key must be a public model field without import/model collisions"
            )
        try:
            definition = SyncDefinition(
                name="sync_feature",
                **{key: value for key, value in raw.items() if key != "version"},
            )
        except ValidationError:
            raise ValueError(
                "Invalid synchronization policy, mode, field name or numeric limit; see the V1 specification"
            ) from None
        return cls(definition)

    @classmethod
    def from_parameters(cls, raw: object) -> "SynchronizationSpec":
        if not isinstance(raw, dict) or "version" in raw:
            raise ValueError(
                "Synchronization parameters must be a mapping without version"
            )
        return cls.from_dict({"version": 1, **raw})

    def to_parameters(self) -> dict[str, object]:
        return self.definition.model_dump(mode="json", exclude={"name"})

    def digest(self) -> str:
        return parameter_mapping_digest(self.to_parameters())


def load_synchronization_spec(path: Path) -> SynchronizationSpec:
    if not path.is_file():
        raise ValueError(f"Synchronization spec not found: {path}")
    if path.stat().st_size > 65_536:
        raise ValueError("Synchronization spec exceeds 64 KiB")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ValueError("Unable to read synchronization spec as UTF-8 YAML") from None
    return SynchronizationSpec.from_dict(raw)
