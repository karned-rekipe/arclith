"""Canonical, provider-neutral input contract for state-machine blueprints."""

from __future__ import annotations

import hashlib
import json
import keyword
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arclith_cli.rename import EntityNames


STATE_MACHINE_SPEC_VERSION = 1
_RESERVED_STATE_FIELDS = {
    "construct",
    "coerce_uuid",
    "copy",
    "created_at",
    "created_by",
    "deleted_at",
    "deleted_by",
    "dict",
    "from_orm",
    "is_deleted",
    "json",
    "model_config",
    "model_fields",
    "parse_file",
    "parse_obj",
    "parse_raw",
    "schema",
    "schema_json",
    "updated_at",
    "updated_by",
    "uuid",
    "validate",
    "version",
}


@dataclass(frozen=True)
class StateTransitionSpec:
    """One named business transition with explicit sources and one target."""

    name: str
    sources: tuple[str, ...]
    target: str

    @classmethod
    def from_dict(cls, raw: object) -> StateTransitionSpec:
        data = _mapping(raw, "state-machine transition")
        _exact_keys(data, {"name", "from", "to"}, "state-machine transition")
        name = _identifier(data["name"], "state-machine transition.name")
        raw_sources = data["from"]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError("state-machine transition.from must be a non-empty list")
        sources = tuple(
            sorted(
                _identifier(source, "state-machine transition.from[]")
                for source in raw_sources
            )
        )
        if len(sources) != len(set(sources)):
            raise ValueError(
                f"state-machine transition {name!r} contains duplicate source states"
            )
        return cls(
            name=name,
            sources=sources,
            target=_identifier(data["to"], "state-machine transition.to"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "from": list(self.sources), "to": self.target}


@dataclass(frozen=True)
class StateMachineSpec:
    """Validated and canonically ordered state-machine specification."""

    version: int
    state_field: str
    initial_state: str
    states: tuple[str, ...]
    transitions: tuple[StateTransitionSpec, ...]

    @classmethod
    def from_dict(cls, raw: object) -> StateMachineSpec:
        data = _mapping(raw, "state-machine spec")
        _exact_keys(
            data,
            {"version", "state_field", "initial_state", "states", "transitions"},
            "state-machine spec",
        )
        version = data["version"]
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != STATE_MACHINE_SPEC_VERSION
        ):
            raise ValueError(
                "state-machine spec.version must be the supported integer version 1"
            )
        state_field = _identifier(data["state_field"], "state-machine state_field")
        if state_field in _RESERVED_STATE_FIELDS or state_field.startswith("model_"):
            raise ValueError(
                f"state-machine state_field {state_field!r} is reserved by Entity/Pydantic"
            )
        raw_states = data["states"]
        if not isinstance(raw_states, list) or len(raw_states) < 2:
            raise ValueError("state-machine states must contain at least two states")
        states = tuple(
            sorted(_identifier(state, "state-machine states[]") for state in raw_states)
        )
        if len(states) != len(set(states)):
            raise ValueError("state-machine states must be unique")
        enum_members = tuple(state.upper() for state in states)
        if len(enum_members) != len(set(enum_members)):
            raise ValueError(
                "state-machine states must have unique generated enum member names"
            )
        initial_state = _identifier(
            data["initial_state"], "state-machine initial_state"
        )
        if initial_state not in states:
            raise ValueError("state-machine initial_state must be declared in states")
        raw_transitions = data["transitions"]
        if not isinstance(raw_transitions, list) or not raw_transitions:
            raise ValueError(
                "state-machine transitions must contain at least one transition"
            )
        transitions = tuple(
            sorted(
                (StateTransitionSpec.from_dict(item) for item in raw_transitions),
                key=lambda item: (item.name, item.sources, item.target),
            )
        )
        _validate_transitions(states, transitions)
        _validate_reachability(initial_state, states, transitions)
        return cls(
            version=version,
            state_field=state_field,
            initial_state=initial_state,
            states=states,
            transitions=transitions,
        )

    @classmethod
    def from_parameters(cls, raw: object) -> StateMachineSpec:
        parameters = _mapping(raw, "state-machine parameters")
        _exact_keys(
            parameters,
            {"state_field", "initial_state", "states", "transitions"},
            "state-machine parameters",
        )
        return cls.from_dict({"version": STATE_MACHINE_SPEC_VERSION, **parameters})

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(transition.name for transition in self.transitions)

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, **self.to_parameters()}

    def to_parameters(self) -> dict[str, object]:
        return {
            "state_field": self.state_field,
            "initial_state": self.initial_state,
            "states": list(self.states),
            "transitions": [transition.to_dict() for transition in self.transitions],
        }

    def digest(self) -> str:
        encoded = json.dumps(
            self.to_parameters(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_state_machine_spec(path: Path) -> StateMachineSpec:
    """Load one spec without retaining its potentially non-portable source path."""

    if not path.is_file():
        raise ValueError(f"State-machine spec not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Unable to read state-machine spec {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in state-machine spec {path}: {exc}") from exc
    return StateMachineSpec.from_dict(raw)


def _validate_transitions(
    states: tuple[str, ...], transitions: tuple[StateTransitionSpec, ...]
) -> None:
    names = tuple(transition.name for transition in transitions)
    if len(names) != len(set(names)):
        raise ValueError("state-machine transition names must be unique")
    symbols = tuple(EntityNames.from_input(name).pascal for name in names)
    if len(symbols) != len(set(symbols)):
        raise ValueError(
            "state-machine transition names must have unique generated class names"
        )
    known = set(states)
    for transition in transitions:
        unknown_sources = sorted(set(transition.sources) - known)
        if unknown_sources:
            raise ValueError(
                f"state-machine transition {transition.name!r} has unknown source "
                f"states: {', '.join(unknown_sources)}"
            )
        if transition.target not in known:
            raise ValueError(
                f"state-machine transition {transition.name!r} has unknown target "
                f"state: {transition.target}"
            )


def _validate_reachability(
    initial_state: str,
    states: tuple[str, ...],
    transitions: tuple[StateTransitionSpec, ...],
) -> None:
    reachable = {initial_state}
    changed = True
    while changed:
        changed = False
        for transition in transitions:
            if (
                reachable.intersection(transition.sources)
                and transition.target not in reachable
            ):
                reachable.add(transition.target)
                changed = True
    unreachable = sorted(set(states) - reachable)
    if unreachable:
        raise ValueError(
            "state-machine states must be reachable from initial_state; unreachable: "
            + ", ".join(unreachable)
        )


def _mapping(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must be a mapping with string keys")
    return raw


def _exact_keys(data: dict[str, Any], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(expected))}")


def _identifier(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty string")
    if not raw.isidentifier() or raw.startswith("_") or keyword.iskeyword(raw):
        raise ValueError(f"{label} must be a public Python identifier")
    return raw
