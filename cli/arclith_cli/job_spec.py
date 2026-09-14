"""Portable job policy; business request/result fields remain extension points."""

import keyword
from dataclasses import dataclass
from pathlib import Path

import yaml

from arclith_cli.feature_manifest import parameter_mapping_digest

JOB_SPEC_VERSION = 1
JOB_OPERATIONS = ("submit", "get_status", "cancel", "retry", "get_result")
_RESERVED_MODELS = {
    "BaseModel",
    "ConfigDict",
    "Field",
    "JobId",
    "JobRecord",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "JobHandler",
    "JobContext",
    "UUID",
}


@dataclass(frozen=True)
class JobSpec:
    request: str
    result: str
    cancellable: bool
    max_attempts: int
    retention_days: int
    version: int = JOB_SPEC_VERSION

    @classmethod
    def from_dict(cls, raw: object) -> "JobSpec":
        if not isinstance(raw, dict) or set(raw) != {
            "version",
            "request",
            "result",
            "cancellable",
            "max_attempts",
            "retention_days",
        }:
            raise ValueError(
                "Job spec requires exactly version, request, result, cancellable, max_attempts, retention_days"
            )
        if type(raw["version"]) is not int or raw["version"] != JOB_SPEC_VERSION:
            raise ValueError("Job spec.version must be integer 1")
        request = _model_name(raw["request"])
        result = _model_name(raw["result"])
        if request == result:
            raise ValueError("Job request and result must have distinct model names")
        if type(raw["cancellable"]) is not bool:
            raise ValueError("Job cancellable must be a boolean")
        for name, maximum in (("max_attempts", 100), ("retention_days", 3650)):
            value = raw[name]
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(
                    f"Job {name} must be an integer between 1 and {maximum}"
                )
        return cls(
            request,
            result,
            raw["cancellable"],
            raw["max_attempts"],
            raw["retention_days"],
        )

    @classmethod
    def from_parameters(cls, raw: object) -> "JobSpec":
        if not isinstance(raw, dict) or "version" in raw:
            raise ValueError("Job parameters must be a mapping without version")
        return cls.from_dict({"version": JOB_SPEC_VERSION, **raw})

    def to_parameters(self) -> dict[str, object]:
        return {
            "request": self.request,
            "result": self.result,
            "cancellable": self.cancellable,
            "max_attempts": self.max_attempts,
            "retention_days": self.retention_days,
        }

    def digest(self) -> str:
        return parameter_mapping_digest(self.to_parameters())


def _model_name(raw: object) -> str:
    if (
        not isinstance(raw, str)
        or not raw.isascii()
        or not raw.isidentifier()
        or not raw[0].isupper()
        or keyword.iskeyword(raw)
        or raw in _RESERVED_MODELS
    ):
        raise ValueError(
            "Job request/result must be distinct public class names without import collisions"
        )
    return raw


def load_job_spec(path: Path) -> JobSpec:
    if not path.is_file():
        raise ValueError(f"Job spec not found: {path}")
    if path.stat().st_size > 65_536:
        raise ValueError("Job spec exceeds 64 KiB")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("Unable to read job spec as UTF-8 YAML") from exc
    return JobSpec.from_dict(raw)
