from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping

if TYPE_CHECKING:
    from arclith_cli.entity_scanner import EntityInfo
    from arclith_cli.project_paths import ProjectPaths


APPLICATION_BLUEPRINT_VERSION = 1


@dataclass(frozen=True)
class ApplicationBlueprintSpec:
    """Declarative contract for one reusable application-level blueprint."""

    name: str
    description: str
    operations: tuple[str, ...]
    version: int = APPLICATION_BLUEPRINT_VERSION
    model_base: Literal["entity", "immutable-record"] = "entity"
    parameterized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "operations": list(self.operations),
            "parameterized": self.parameterized,
        }


CRUD_BLUEPRINT = ApplicationBlueprintSpec(
    name="crud",
    description="Cycle de vie CRUD explicite pour une entité métier.",
    operations=("create", "get", "list", "update", "delete"),
)

APPEND_ONLY_BLUEPRINT = ApplicationBlueprintSpec(
    name="append-only",
    description="Faits immuables avec append idempotent et conflit explicite.",
    operations=("append",),
    model_base="immutable-record",
)

STATE_MACHINE_BLUEPRINT = ApplicationBlueprintSpec(
    name="state-machine",
    description="Cycle de vie typé avec transitions métier définies par une spec.",
    operations=(),
    parameterized=True,
)

APPLICATION_BLUEPRINT_CATALOG = (
    CRUD_BLUEPRINT,
    APPEND_ONLY_BLUEPRINT,
    STATE_MACHINE_BLUEPRINT,
)


def get_application_blueprint(name: str) -> ApplicationBlueprintSpec:
    normalized = name.strip().lower()
    blueprint = next(
        (item for item in APPLICATION_BLUEPRINT_CATALOG if item.name == normalized),
        None,
    )
    if blueprint is None:
        supported = ", ".join(item.name for item in APPLICATION_BLUEPRINT_CATALOG)
        raise ValueError(
            f"Unknown application blueprint {name!r}; expected one of: {supported}"
        )
    return blueprint


def application_blueprint_catalog_as_dict() -> list[dict[str, object]]:
    return [item.to_dict() for item in APPLICATION_BLUEPRINT_CATALOG]


def render_application_blueprint(
    blueprint: ApplicationBlueprintSpec,
    paths: ProjectPaths,
    entity: EntityInfo,
    feature: str,
    parameters: Mapping[str, Any] | None = None,
    *,
    creating_entity: bool = False,
) -> dict[Path, str]:
    """Render one catalogued application blueprint."""
    if blueprint.name == "crud":
        from arclith_cli.crud_blueprint import render_crud_blueprint

        return render_crud_blueprint(paths, entity, feature)
    if blueprint.name == "append-only":
        from arclith_cli.append_only_blueprint import render_append_only_blueprint

        return render_append_only_blueprint(paths, entity, feature)
    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_blueprint import render_state_machine_blueprint
        from arclith_cli.state_machine_spec import StateMachineSpec

        spec = StateMachineSpec.from_parameters(parameters)
        return render_state_machine_blueprint(
            paths,
            entity,
            feature,
            spec,
            creating_entity=creating_entity,
        )
    raise ValueError(f"No renderer for application blueprint {blueprint.name!r}")


def application_blueprint_digest(blueprint: ApplicationBlueprintSpec) -> str:
    from arclith_cli.entity_scanner import EntityInfo
    from arclith_cli.project_paths import ProjectPaths

    root = Path("/application-blueprint")
    package_root = root / "src" / "application_package"
    paths = ProjectPaths(
        root=root,
        package_root=package_root,
        package_name="application_package",
    )
    entity = EntityInfo(
        pascal="Entity",
        snake="entity",
        file_path=package_root / "domain" / "models" / "entity.py",
        model_base=blueprint.model_base,
    )
    parameters: dict[str, object] | None = None
    if blueprint.name == "state-machine":
        parameters = {
            "state_field": "status",
            "initial_state": "draft",
            "states": ["approved", "draft"],
            "transitions": [{"name": "approve", "from": ["draft"], "to": "approved"}],
        }
    rendered = render_application_blueprint(
        blueprint,
        paths,
        entity,
        "feature",
        parameters,
        creating_entity=True,
    )
    entity_template: str | None = None
    existing_entity_validation_version: int | None = None
    renderer_contract: str | None = None
    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_entity import (
            STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION,
            render_state_machine_entity,
        )
        from arclith_cli.state_machine_spec import StateMachineSpec

        entity_template = render_state_machine_entity(
            paths,
            entity,
            StateMachineSpec.from_parameters(parameters),
        )
        existing_entity_validation_version = (
            STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION
        )
        renderer_contract = _state_machine_renderer_contract_digest()
    blueprint_contract = blueprint.to_dict()
    if not blueprint.parameterized:
        # Keep digests recorded by pre-parameterized CRUD/append-only recipes valid.
        blueprint_contract.pop("parameterized")
    digest_contract: dict[str, object] = {
        "blueprint": blueprint_contract,
        "files": {
            path.relative_to(root).as_posix(): content
            for path, content in sorted(rendered.items())
        },
    }
    if (
        entity_template is not None
        and existing_entity_validation_version is not None
        and renderer_contract is not None
    ):
        digest_contract["entity_template"] = entity_template
        digest_contract["existing_entity_validation_version"] = (
            existing_entity_validation_version
        )
        digest_contract["renderer_contract"] = renderer_contract
    payload = json.dumps(
        digest_contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _state_machine_renderer_contract_digest() -> str:
    """Hash all state-machine rendering and existing-entity validation branches."""
    import inspect

    from arclith_cli import state_machine_blueprint, state_machine_entity

    source = "\0".join(
        inspect.getsource(module)
        for module in (state_machine_blueprint, state_machine_entity)
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(source).hexdigest()


def canonical_blueprint_parameters(
    blueprint: ApplicationBlueprintSpec,
    raw: object,
) -> dict[str, Any] | None:
    """Validate and canonicalize optional blueprint-specific parameters."""

    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_spec import StateMachineSpec

        return StateMachineSpec.from_parameters(raw).to_parameters()
    if raw is not None:
        raise ValueError(f"Blueprint {blueprint.name!r} does not accept parameters")
    return None


def application_parameters_digest(
    blueprint: ApplicationBlueprintSpec,
    parameters: Mapping[str, Any] | None,
) -> str | None:
    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_spec import StateMachineSpec

        return StateMachineSpec.from_parameters(parameters).digest()
    if parameters is not None:
        raise ValueError(f"Blueprint {blueprint.name!r} does not accept parameters")
    return None
