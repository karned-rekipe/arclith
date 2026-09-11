from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "operations": list(self.operations),
        }


CRUD_BLUEPRINT = ApplicationBlueprintSpec(
    name="crud",
    description="Cycle de vie CRUD explicite pour une entité métier.",
    operations=("create", "get", "list", "update", "delete"),
)

APPLICATION_BLUEPRINT_CATALOG = (CRUD_BLUEPRINT,)


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
) -> dict[Path, str]:
    """Render one catalogued application blueprint."""
    if blueprint.name == "crud":
        from arclith_cli.crud_blueprint import render_crud_blueprint

        return render_crud_blueprint(paths, entity, feature)
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
    )
    rendered = render_application_blueprint(blueprint, paths, entity, "feature")
    payload = json.dumps(
        {
            "blueprint": blueprint.to_dict(),
            "files": {
                path.relative_to(root).as_posix(): content
                for path, content in sorted(rendered.items())
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
