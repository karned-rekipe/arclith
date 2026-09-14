import keyword
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import typer
from rich.console import Console

from arclith_cli.atomic_writes import FilePublication, write_new_text_file
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
    TARGETED_FEATURE_MANIFEST_VERSION,
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
    entity: EntityInfo | None
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
    entity: EntityInfo | None
    feature: str
    manifest_path: Path
    changed: tuple[Path, ...]
    preserved: tuple[Path, ...]


@dataclass(frozen=True)
class _CreatedDirectory:
    """Filesystem identity of a directory created by the current command."""

    path: Path
    device: int
    inode: int


def plan_application_blueprint(
    project_dir: Path,
    *,
    blueprint_name: str,
    entity_name: str | None,
    feature_name: str | None,
    parameters: Mapping[str, Any] | None = None,
) -> ApplicationBlueprintPlan:
    entity = _require_entity(project_dir, entity_name) if entity_name is not None else None
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
    entity: EntityInfo | None,
    feature_name: str | None,
    parameters: Mapping[str, Any] | None = None,
    creating_entity: bool = False,
    project_paths: ProjectPaths | None = None,
    expected_empty_initializers: tuple[Path, ...] = (),
) -> ApplicationBlueprintPlan:
    if entity is None and (blueprint.name != "job" or not feature_name):
        raise ValueError("Only job supports --no-entity and it requires --feature")
    if entity is not None and blueprint.name != "job" and entity.model_base != blueprint.model_base:
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
    entity_module = entity.file_path.stem if entity is not None else ""
    if entity is not None and (not entity_module.isidentifier() or keyword.iskeyword(entity_module)):
        raise ValueError(
            f"Entity module name {entity_module!r} must be a valid, non-keyword "
            "Python identifier"
        )
    if entity is not None and keyword.iskeyword(entity.snake):
        raise ValueError(
            f"Entity {entity.pascal!r} normalizes to the reserved Python keyword "
            f"{entity.snake!r}"
        )
    feature = _feature_name(feature_name or (entity.snake if entity is not None else ""))
    canonical_parameters = canonical_blueprint_parameters(blueprint, parameters)
    parameter_digest = application_parameters_digest(blueprint, canonical_parameters)
    operations = blueprint.operations
    if blueprint.name == "state-machine":
        from arclith_cli.state_machine_spec import StateMachineSpec

        operations = StateMachineSpec.from_parameters(canonical_parameters).operations
    manifest_version = (
        TARGETED_FEATURE_MANIFEST_VERSION if blueprint.name == "job" else
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
        ) if entity is not None else None,
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
    if blueprint.name == "job":
        raise ValueError("Use add-blueprint job with --entity or --no-entity; job is not an entity profile")
    if blueprint.name == "synchronization":
        raise ValueError("Use add-blueprint synchronization with --entity and --spec; synchronization is not an entity profile")
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
    written: list[FilePublication] = []
    directories: list[_CreatedDirectory] = []
    try:
        _create_parent_directories(
            plan.project_dir,
            tuple(plan.files),
            created=directories,
        )
        for path, content in plan.files.items():
            if path == plan.manifest_path:
                continue
            if plan.originals[path] is not None:
                # Entity/new-project initializers are already the exact empty
                # snapshot anticipated by the plan; no rewrite is necessary.
                continue
            written.append(write_new_text_file(path, content))
        if plan.manifest_path in plan.files:
            written.append(save_feature_manifest(plan.manifest, plan.manifest_path))
    except Exception:
        _restore_written_files(
            written,
            expected=plan.files,
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
    if plan.entity is None:
        raise ValueError("Entity creation requires an entity-scoped plan")
    entity_path = plan.entity.file_path
    tracked = (entity_path, *_entity_initializer_paths(paths))
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
    directories: list[_CreatedDirectory] = []
    created_files: list[FilePublication] = []
    try:
        _create_parent_directories(
            plan.project_dir,
            tracked,
            created=directories,
        )
        created = add_entity_cmd(
            project_dir=plan.project_dir,
            entity_name=entity_name,
            model_base=plan.entity.model_base,
            entity_content=entity_content,
            created_files=created_files,
        )
        apply_application_blueprint(plan)
    except Exception:
        _restore_written_files(
            created_files,
            expected=expected,
        )
        _remove_empty_directories(directories)
        raise
    return created


def _create_parent_directories(
    project_dir: Path,
    targets: tuple[Path, ...],
    *,
    created: list[_CreatedDirectory],
) -> None:
    missing: set[Path] = set()
    for target in targets:
        for parent in target.parents:
            if parent == project_dir:
                break
            if not parent.exists():
                missing.add(parent)
    for directory in sorted(missing, key=lambda path: len(path.parts)):
        try:
            directory.mkdir()
        except FileExistsError:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(
                    "Application blueprint parent must be a directory without "
                    f"symlinks: {directory.relative_to(project_dir)}"
                ) from None
            continue
        identity = directory.lstat()
        created.append(
            _CreatedDirectory(
                path=directory,
                device=identity.st_dev,
                inode=identity.st_ino,
            )
        )


def _restore_written_files(
    publications: list[FilePublication],
    *,
    expected: Mapping[Path, str | bytes | None],
) -> None:
    for publication in reversed(publications):
        planned = expected.get(publication.path)
        planned_bytes = planned.encode("utf-8") if isinstance(planned, str) else planned
        if planned_bytes is not None:
            _remove_unchanged_publication(publication, planned_bytes)


def _remove_unchanged_publication(
    publication: FilePublication,
    planned: bytes,
) -> None:
    """Atomically detach a path, then delete only the inode we published."""

    try:
        quarantine_dir = Path(
            tempfile.mkdtemp(
                dir=publication.path.parent,
                prefix=f".{publication.path.name}.",
                suffix=".rollback",
            )
        )
    except OSError:
        return
    quarantine = quarantine_dir / "published"
    try:
        try:
            publication.path.rename(quarantine)
        except OSError:
            return
        try:
            identity = quarantine.lstat()
            unchanged = (
                (identity.st_dev, identity.st_ino)
                == (publication.device, publication.inode)
                and quarantine.read_bytes() == planned
            )
        except OSError:
            unchanged = False
        if unchanged:
            try:
                quarantine.unlink()
            except OSError:
                # Rollback cleanup is best-effort; keep the private quarantine
                # rather than mask the application error being compensated.
                pass
            return
        _restore_quarantined_file(quarantine, publication.path)
    finally:
        try:
            quarantine_dir.rmdir()
        except OSError:
            # A non-empty quarantine preserves concurrently written content.
            pass


def _restore_quarantined_file(quarantine: Path, target: Path) -> None:
    """Restore a moved concurrent regular file without replacing a newer path."""

    if quarantine.is_symlink() or not quarantine.is_file():
        return
    try:
        os.link(quarantine, target)
    except OSError:
        return
    try:
        quarantine.unlink()
    except OSError:
        # Both hard links preserve the same bytes; cleanup remains best-effort.
        pass


def _remove_empty_directories(directories: list[_CreatedDirectory]) -> None:
    for created in reversed(directories):
        try:
            identity = created.path.lstat()
            if (identity.st_dev, identity.st_ino) != (
                created.device,
                created.inode,
            ):
                continue
            created.path.rmdir()
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
    entity_name: str | None,
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
            f"{plan.entity.pascal if plan.entity is not None else plan.feature}.[/bold green]"
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
