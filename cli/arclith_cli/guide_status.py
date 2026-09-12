import tomllib
from pathlib import Path
from typing import Any

import yaml

from arclith_cli.entity_scanner import scan_entities
from arclith_cli.feature_manifest import load_feature_manifest
from arclith_cli.guide_models import (
    GuidePlanError,
    ProjectFeature,
    ProjectOverview,
)
from arclith_cli.project_paths import detect_project_paths
from arclith_cli.recipe import RECIPE_FILENAME, RecipeError, load_recipe


def find_project_root(start: Path) -> Path | None:
    """Find the nearest Arclith project without crossing the filesystem root."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if _is_arclith_project(candidate):
            return candidate
    return None


def inspect_project(project_dir: Path) -> ProjectOverview:
    """Describe the generated project from its current on-disk state."""
    root = project_dir.resolve()
    if not _is_arclith_project(root):
        raise GuidePlanError(f"Projet Arclith introuvable : {root}")
    paths = detect_project_paths(root)
    issues: list[str] = []
    name = _project_name(root, issues)
    entities = tuple(entity.pascal for entity in scan_entities(root))
    usecases = _scan_usecases(paths.inbound_ports)
    features = _scan_features(root, issues)
    adapters = _scan_adapters(root, issues)
    recipe_path = root / RECIPE_FILENAME
    if recipe_path.is_file():
        try:
            load_recipe(recipe_path)
        except (OSError, RecipeError) as exc:
            issues.append(f"Recette invalide : {exc}")
    else:
        issues.append(f"Recette absente : {RECIPE_FILENAME}")
    return ProjectOverview(
        root=root,
        name=name,
        package=paths.package_name or root.name,
        entities=entities,
        usecases=usecases,
        features=features,
        adapters=adapters,
        issues=tuple(issues),
    )


def _is_arclith_project(candidate: Path) -> bool:
    if not (candidate / "pyproject.toml").is_file():
        return False
    paths = detect_project_paths(candidate)
    return (paths.package_root / "domain" / "models").is_dir()


def _project_name(root: Path, issues: list[str]) -> str:
    try:
        raw = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        issues.append(f"pyproject.toml invalide : {exc}")
        return root.name
    project = raw.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            return name
    issues.append("Nom de projet absent de pyproject.toml.")
    return root.name


def _scan_usecases(inbound_ports: Path) -> tuple[str, ...]:
    if not inbound_ports.is_dir():
        return ()
    return tuple(
        path.stem
        for path in sorted(inbound_ports.glob("*.py"))
        if not path.name.startswith("_")
    )


def _scan_features(root: Path, issues: list[str]) -> tuple[ProjectFeature, ...]:
    manifests_dir = root / ".arclith" / "features"
    if not manifests_dir.is_dir():
        return ()
    features: list[ProjectFeature] = []
    for path in sorted(manifests_dir.glob("*.yaml")):
        try:
            manifest = load_feature_manifest(path)
        except (OSError, ValueError) as exc:
            issues.append(f"Feature invalide ({path.name}) : {exc}")
            continue
        features.append(
            ProjectFeature(
                name=manifest.feature,
                entity=manifest.entity.name,
                blueprint=manifest.blueprint.name,
            )
        )
    return tuple(features)


def _scan_adapters(root: Path, issues: list[str]) -> tuple[str, ...]:
    manifests_dir = root / ".arclith" / "blueprints"
    if not manifests_dir.is_dir():
        return ()
    adapters: list[str] = []
    for path in sorted(manifests_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            capability = _manifest_string(raw, "capability")
            adapter = _manifest_string(raw, "adapter")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            issues.append(f"Adapter invalide ({path.name}) : {exc}")
            continue
        adapters.append(f"{capability}/{adapter}")
    return tuple(adapters)


def _manifest_string(raw: Any, key: str) -> str:
    if not isinstance(raw, dict):
        raise ValueError("le manifeste doit être un mapping")
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"champ {key!r} absent ou invalide")
    return value
