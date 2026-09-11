import keyword
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from arclith_cli.application_blueprints import (
    ApplicationBlueprintSpec,
    get_application_blueprint,
    render_application_blueprint,
)
from arclith_cli.entity_scanner import EntityInfo, scan_entities
from arclith_cli.feature_manifest import (
    FEATURE_MANIFEST_VERSION,
    FeatureBlueprint,
    FeatureEntity,
    FeatureManifest,
    load_feature_manifest,
    render_feature_manifest,
    save_feature_manifest,
)
from arclith_cli.project_paths import detect_project_paths
from arclith_cli.rename import EntityNames

console = Console()


@dataclass(frozen=True)
class ApplicationBlueprintPlan:
    project_dir: Path
    blueprint: ApplicationBlueprintSpec
    entity: EntityInfo
    feature: str
    manifest: FeatureManifest
    manifest_path: Path
    files: dict[Path, str]
    preserved: tuple[Path, ...]
    originals: dict[Path, bytes | None]


@dataclass(frozen=True)
class ApplicationBlueprintResult:
    blueprint: ApplicationBlueprintSpec
    entity: EntityInfo
    feature: str
    manifest_path: Path
    changed: tuple[Path, ...]
    preserved: tuple[Path, ...]


def plan_application_blueprint(
    project_dir: Path,
    *,
    blueprint_name: str,
    entity_name: str,
    feature_name: str | None,
) -> ApplicationBlueprintPlan:
    entity = _require_entity(project_dir, entity_name)
    return plan_application_blueprint_for_entity(
        project_dir,
        blueprint=get_application_blueprint(blueprint_name),
        entity=entity,
        feature_name=feature_name,
    )


def plan_application_blueprint_for_entity(
    project_dir: Path,
    *,
    blueprint: ApplicationBlueprintSpec,
    entity: EntityInfo,
    feature_name: str | None,
) -> ApplicationBlueprintPlan:
    paths = detect_project_paths(project_dir)
    feature = _feature_name(feature_name or entity.snake)
    manifest = FeatureManifest(
        version=FEATURE_MANIFEST_VERSION,
        feature=feature,
        entity=FeatureEntity(
            name=entity.pascal,
            module=paths.import_path("domain", "models", entity.file_path.stem),
        ),
        blueprint=FeatureBlueprint(name=blueprint.name, version=blueprint.version),
        operations=blueprint.operations,
    )
    manifest_path = project_dir / ".arclith" / "features" / f"{feature}.yaml"
    rendered = render_application_blueprint(blueprint, paths, entity, feature)
    invalid_targets = sorted(
        path for path in rendered if path.exists() and not path.is_file()
    )
    if invalid_targets:
        relative = ", ".join(
            str(path.relative_to(project_dir)) for path in invalid_targets
        )
        raise ValueError(f"Application blueprint target is not a file: {relative}")
    installed = manifest_path.is_file()
    if installed and load_feature_manifest(manifest_path) != manifest:
        raise ValueError(
            f"Feature {feature!r} already has a different canonical manifest"
        )
    if not installed:
        collisions = sorted(
            path for path in rendered if path.exists() and path.name != "__init__.py"
        )
        if collisions:
            relative = ", ".join(
                str(path.relative_to(project_dir)) for path in collisions
            )
            raise ValueError(
                f"Application blueprint target already exists before first install: {relative}"
            )

    preserved = tuple(sorted(path for path in rendered if path.exists()))
    files = {path: content for path, content in rendered.items() if not path.exists()}
    if not installed:
        files[manifest_path] = render_feature_manifest(manifest)
    originals = {path: path.read_bytes() if path.is_file() else None for path in files}
    return ApplicationBlueprintPlan(
        project_dir=project_dir,
        blueprint=blueprint,
        entity=entity,
        feature=feature,
        manifest=manifest,
        manifest_path=manifest_path,
        files=files,
        preserved=preserved,
        originals=originals,
    )


def apply_application_blueprint(
    plan: ApplicationBlueprintPlan,
) -> tuple[Path, ...]:
    for path, original in plan.originals.items():
        current = path.read_bytes() if path.is_file() else None
        if current != original or (path.exists() and not path.is_file()):
            raise ValueError(
                f"File changed after blueprint planning; rerun the command: {path}"
            )
    for path, content in plan.files.items():
        if path == plan.manifest_path:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if plan.manifest_path in plan.files:
        save_feature_manifest(plan.manifest, plan.manifest_path)
    return tuple(plan.files)


def add_application_blueprint_cmd(
    *,
    project_dir: Path,
    blueprint_name: str,
    entity_name: str,
    feature_name: str | None,
    dry_run: bool,
) -> ApplicationBlueprintResult:
    plan = plan_application_blueprint(
        project_dir,
        blueprint_name=blueprint_name,
        entity_name=entity_name,
        feature_name=feature_name,
    )
    for path in plan.files:
        console.print(f"create [bold]{path.relative_to(project_dir)}[/bold]")
    for path in plan.preserved:
        console.print(f"preserve [dim]{path.relative_to(project_dir)}[/dim]")
    changed = () if dry_run else apply_application_blueprint(plan)
    if dry_run:
        console.print("[cyan]Dry run: aucun fichier ni manifest modifié.[/cyan]")
    else:
        console.print(
            f"[bold green]✓ Blueprint {plan.blueprint.name} appliqué à "
            f"{plan.entity.pascal}.[/bold green]"
        )
    return ApplicationBlueprintResult(
        blueprint=plan.blueprint,
        entity=plan.entity,
        feature=plan.feature,
        manifest_path=plan.manifest_path,
        changed=changed,
        preserved=plan.preserved,
    )


def _require_entity(project_dir: Path, raw_name: str) -> EntityInfo:
    normalized = EntityNames.from_input(raw_name.strip())
    entities = scan_entities(project_dir)
    entity = next(
        (
            item
            for item in entities
            if item.pascal == normalized.pascal or item.snake == normalized.snake
        ),
        None,
    )
    if entity is not None:
        return entity
    detected = ", ".join(item.pascal for item in entities) or "aucune"
    console.print(
        f"[red]✗[/red] Entité introuvable : [bold]{raw_name}[/bold]. "
        f"Entités détectées : {detected}."
    )
    raise typer.Exit(1)


def _feature_name(raw: str) -> str:
    normalized = raw.strip().lower().replace("-", "_")
    if (
        not normalized.isidentifier()
        or normalized.startswith("_")
        or keyword.iskeyword(normalized)
    ):
        raise ValueError(f"Invalid public feature name: {raw!r}")
    return normalized
