import keyword
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import typer
from rich.console import Console

from arclith_cli.application_blueprints import (
    ApplicationBlueprintSpec,
    application_blueprint_digest,
    application_parameters_digest,
    canonical_blueprint_parameters,
    get_application_blueprint,
    render_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd, validated_entity_names
from arclith_cli.entity_scanner import EntityInfo, scan_blueprint_models
from arclith_cli.feature_manifest import (
    FEATURE_MANIFEST_VERSION,
    PARAMETERIZED_FEATURE_MANIFEST_VERSION,
    FeatureBlueprint,
    FeatureDigests,
    FeatureEntity,
    FeatureManifest,
    load_feature_manifest,
    render_feature_manifest,
    save_feature_manifest,
)
from arclith_cli.project_paths import ProjectPaths, detect_project_paths
from arclith_cli.rename import EntityNames
from arclith_cli.scaffold_templates import render_entity_template

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
    parameters: dict[str, Any] | None = None


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
    parameters: Mapping[str, Any] | None = None,
) -> ApplicationBlueprintPlan:
    entity = _require_entity(project_dir, entity_name)
    return plan_application_blueprint_for_entity(
        project_dir,
        blueprint=get_application_blueprint(blueprint_name),
        entity=entity,
        feature_name=feature_name,
        parameters=parameters,
    )


def plan_application_blueprint_for_entity(
    project_dir: Path,
    *,
    blueprint: ApplicationBlueprintSpec,
    entity: EntityInfo,
    feature_name: str | None,
    parameters: Mapping[str, Any] | None = None,
    creating_entity: bool = False,
    project_paths: ProjectPaths | None = None,
    expected_empty_initializers: tuple[Path, ...] = (),
) -> ApplicationBlueprintPlan:
    if entity.model_base != blueprint.model_base:
        expected = (
            "ImmutableRecord"
            if blueprint.model_base == "immutable-record"
            else "Entity"
        )
        actual = (
            "ImmutableRecord" if entity.model_base == "immutable-record" else "Entity"
        )
        raise ValueError(
            f"Blueprint {blueprint.name!r} requires a model based on {expected}; "
            f"{entity.pascal} is based on {actual}"
        )
    paths = project_paths or detect_project_paths(project_dir)
    entity_module = entity.file_path.stem
    if not entity_module.isidentifier() or keyword.iskeyword(entity_module):
        raise ValueError(
            f"Entity module name {entity_module!r} must be a valid, non-keyword "
            "Python identifier"
        )
    if keyword.iskeyword(entity.snake):
        raise ValueError(
            f"Entity {entity.pascal!r} normalizes to the reserved Python keyword "
            f"{entity.snake!r}"
        )
    feature = _feature_name(feature_name or entity.snake)
    canonical_parameters = canonical_blueprint_parameters(blueprint, parameters)
    parameter_digest = application_parameters_digest(blueprint, canonical_parameters)
    operations = blueprint.operations
    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_spec import StateMachineSpec

        operations = StateMachineSpec.from_parameters(canonical_parameters).operations
    manifest_version = (
        PARAMETERIZED_FEATURE_MANIFEST_VERSION
        if canonical_parameters is not None
        else FEATURE_MANIFEST_VERSION
    )
    manifest = FeatureManifest(
        version=manifest_version,
        feature=feature,
        entity=FeatureEntity(
            name=entity.pascal,
            module=paths.import_path("domain", "models", entity.file_path.stem),
        ),
        blueprint=FeatureBlueprint(name=blueprint.name, version=blueprint.version),
        operations=operations,
        parameters=canonical_parameters,
        digests=(
            FeatureDigests(
                template=application_blueprint_digest(blueprint),
                parameters=parameter_digest,
            )
            if parameter_digest is not None
            else None
        ),
    )
    manifest_path = project_dir / ".arclith" / "features" / f"{feature}.yaml"
    rendered = render_application_blueprint(
        blueprint,
        paths,
        entity,
        feature,
        canonical_parameters,
        creating_entity=creating_entity,
    )
    _validate_target_paths(project_dir, (*rendered, manifest_path))
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
    if creating_entity:
        # Record only the exact empty initializer snapshots written between
        # planning and application by ``add_entity_cmd`` and, for ``new``, ``init``.
        expected_initializers = {
            *_entity_initializer_paths(paths),
            *expected_empty_initializers,
        }
        for initializer in expected_initializers:
            if initializer in originals and originals[initializer] is None:
                originals[initializer] = b""
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
        parameters=canonical_parameters,
    )


def plan_application_profile_for_new_entity(
    project_dir: Path,
    *,
    profile_name: str,
    entity_name: str,
    parameters: Mapping[str, Any] | None = None,
    project_paths: ProjectPaths | None = None,
    expected_empty_initializers: tuple[Path, ...] = (),
) -> ApplicationBlueprintPlan | None:
    """Preflight an optional application profile before creating its entity."""
    names = validated_entity_names(entity_name)
    if profile_name == "minimal":
        if parameters is not None:
            raise ValueError("Profile 'minimal' does not accept parameters")
        return None
    paths = project_paths or detect_project_paths(project_dir)
    blueprint = get_application_blueprint(profile_name)
    return plan_application_blueprint_for_entity(
        project_dir,
        blueprint=blueprint,
        entity=EntityInfo(
            pascal=names.pascal,
            snake=names.snake,
            file_path=paths.domain_models / f"{names.snake}.py",
            model_base=blueprint.model_base,
        ),
        feature_name=names.snake,
        parameters=parameters,
        creating_entity=True,
        project_paths=paths,
        expected_empty_initializers=expected_empty_initializers,
    )


def _entity_initializer_paths(paths: ProjectPaths) -> tuple[Path, ...]:
    """Mirror the package initializers created by ``add_entity_cmd``."""
    stop_at = (
        paths.package_root.parent
        if paths.package_name is not None
        else paths.package_root
    )
    directories = [paths.domain_models]
    for parent in paths.domain_models.parents:
        if parent == stop_at:
            break
        directories.append(parent)
    return tuple(directory / "__init__.py" for directory in directories)


def apply_application_blueprint(
    plan: ApplicationBlueprintPlan,
) -> tuple[Path, ...]:
    _validate_target_paths(plan.project_dir, tuple(plan.files))
    for path, original in plan.originals.items():
        current = path.read_bytes() if path.is_file() else None
        if current != original or (path.exists() and not path.is_file()):
            raise ValueError(
                f"File changed after blueprint planning; rerun the command: {path}"
            )
    written: list[Path] = []
    directories = _missing_parent_directories(plan.project_dir, tuple(plan.files))
    try:
        for path, content in plan.files.items():
            if path == plan.manifest_path:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
        if plan.manifest_path in plan.files:
            save_feature_manifest(plan.manifest, plan.manifest_path)
            written.append(plan.manifest_path)
    except Exception:
        _restore_written_files(
            written,
            expected=plan.files,
            originals=plan.originals,
        )
        _remove_empty_directories(directories)
        raise
    return tuple(plan.files)


def create_entity_with_application_blueprint(
    plan: ApplicationBlueprintPlan,
    *,
    entity_name: str,
    entity_content: str | None,
) -> Path:
    """Create an entity and compensate it if blueprint application fails."""

    paths = detect_project_paths(plan.project_dir)
    entity_path = plan.entity.file_path
    tracked = (entity_path, *_entity_initializer_paths(paths))
    originals = {
        path: path.read_bytes() if path.is_file() else None for path in tracked
    }
    expected = {
        entity_path: (
            entity_content
            if entity_content is not None
            else render_entity_template(
                class_name=plan.entity.pascal,
                model_base=plan.entity.model_base,
            )
        ).encode("utf-8"),
        **{
            initializer: b""
            for initializer in tracked
            if initializer != entity_path
        },
    }
    directories = _missing_parent_directories(plan.project_dir, tracked)
    try:
        created = add_entity_cmd(
            project_dir=plan.project_dir,
            entity_name=entity_name,
            model_base=plan.entity.model_base,
            entity_content=entity_content,
        )
        apply_application_blueprint(plan)
    except Exception:
        _restore_written_files(
            list(tracked),
            expected=expected,
            originals=originals,
        )
        _remove_empty_directories(directories)
        raise
    return created


def _missing_parent_directories(
    project_dir: Path,
    targets: tuple[Path, ...],
) -> tuple[Path, ...]:
    missing: set[Path] = set()
    for target in targets:
        for parent in target.parents:
            if parent == project_dir:
                break
            if not parent.exists():
                missing.add(parent)
    return tuple(sorted(missing, key=lambda path: len(path.parts), reverse=True))


def _restore_written_files(
    paths: list[Path],
    *,
    expected: Mapping[Path, str | bytes | None],
    originals: Mapping[Path, bytes | None],
) -> None:
    for path in reversed(paths):
        planned = expected.get(path)
        planned_bytes = planned.encode("utf-8") if isinstance(planned, str) else planned
        try:
            current = path.read_bytes() if path.is_file() else None
            if planned_bytes is None or current != planned_bytes:
                continue
            original = originals.get(path)
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)
        except OSError:
            # Preserve the primary failure and never broaden cleanup targets.
            continue


def _remove_empty_directories(directories: tuple[Path, ...]) -> None:
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            continue


def _validate_target_paths(project_dir: Path, targets: tuple[Path, ...]) -> None:
    """Reject target and ancestor collisions before any filesystem write."""
    for target in targets:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(
                f"Application blueprint target is not a file: {target.relative_to(project_dir)}"
            )
        for parent in target.parents:
            if parent == project_dir:
                break
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise ValueError(
                    "Application blueprint parent must be a directory without symlinks: "
                    f"{parent.relative_to(project_dir)}"
                )


def add_application_blueprint_cmd(
    *,
    project_dir: Path,
    blueprint_name: str,
    entity_name: str,
    feature_name: str | None,
    dry_run: bool,
    parameters: Mapping[str, Any] | None = None,
) -> ApplicationBlueprintResult:
    plan = plan_application_blueprint(
        project_dir,
        blueprint_name=blueprint_name,
        entity_name=entity_name,
        feature_name=feature_name,
        parameters=parameters,
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
    entities = scan_blueprint_models(project_dir)
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
