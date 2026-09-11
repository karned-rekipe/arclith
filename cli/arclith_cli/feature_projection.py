"""Project declared application features onto explicitly installed transports."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from arclith_cli.application_blueprints import get_application_blueprint
from arclith_cli.binding_contract import public_identifier
from arclith_cli.binding_rendering import ApplicationErrorMapping
from arclith_cli.entity_scanner import scan_entities
from arclith_cli.feature_manifest import FeatureManifest, load_feature_manifest
from arclith_cli.http_paths import http_path_parameters
from arclith_cli.project_paths import ProjectPaths, detect_project_paths
from arclith_cli.usecase_binding import (
    BindingBatchPlan,
    BindingContainer,
    BindingRequest,
    apply_binding,
    plan_bindings,
)

FEATURE_PROJECTION_VERSION = 1


@dataclass(frozen=True)
class FeatureProjectionPlan:
    """A validated, filesystem-neutral plan for one feature projection."""

    feature: FeatureManifest
    via: str
    http_path: str
    binding_plan: BindingBatchPlan


@dataclass(frozen=True)
class FeatureProjectionResult:
    """Paths affected or preserved by an applied feature projection."""

    feature: FeatureManifest
    via: str
    http_path: str
    changed: tuple[Path, ...]
    preserved: tuple[Path, ...]


def plan_feature_projection(
    project_dir: Path,
    *,
    feature_name: str,
    via: str,
    http_path: str | None,
) -> FeatureProjectionPlan:
    """Consume one application feature manifest and plan its transport projection."""
    feature = public_identifier(feature_name)
    manifest = load_feature_manifest(
        project_dir / ".arclith" / "features" / f"{feature}.yaml"
    )
    if manifest.feature != feature:
        raise ValueError(
            f"Feature manifest declares {manifest.feature!r}, expected {feature!r}"
        )
    if via != "fastapi":
        raise ValueError("Supported feature projections: fastapi")
    blueprint = get_application_blueprint(manifest.blueprint.name)
    if blueprint.name != "crud":
        raise ValueError(
            "Supported application blueprints for FastAPI feature projection: crud"
        )
    if (
        manifest.blueprint.version != blueprint.version
        or manifest.operations != blueprint.operations
    ):
        raise ValueError("Feature manifest does not match its canonical blueprint")
    collection_path = _collection_path(http_path, feature)
    paths = detect_project_paths(project_dir)
    _validate_crud_application_contract(project_dir, paths, manifest)
    container_module = paths.import_path(
        "infrastructure", "containers", manifest.feature
    )
    errors_module = paths.import_path("domain", "errors", manifest.feature)
    not_found = ApplicationErrorMapping(
        module=errors_module,
        error=f"{manifest.entity.name}NotFoundError",
        status_code=404,
        description=f"{manifest.entity.name} not found",
    )
    version_conflict = ApplicationErrorMapping(
        module=errors_module,
        error=f"{manifest.entity.name}VersionConflictError",
        status_code=409,
        description=f"{manifest.entity.name} version conflict",
    )
    requests = _crud_fastapi_requests(
        manifest,
        collection_path=collection_path,
        container_module=container_module,
        not_found=not_found,
        version_conflict=version_conflict,
    )
    return FeatureProjectionPlan(
        feature=manifest,
        via=via,
        http_path=collection_path,
        binding_plan=plan_bindings(project_dir, requests),
    )


def apply_feature_projection(plan: FeatureProjectionPlan) -> tuple[Path, ...]:
    """Apply one fully preflighted feature projection."""
    return apply_binding(plan.binding_plan)


def add_feature_projection_cmd(
    project_dir: Path,
    *,
    feature_name: str,
    via: str,
    http_path: str | None,
    dry_run: bool,
) -> FeatureProjectionResult:
    plan = plan_feature_projection(
        project_dir,
        feature_name=feature_name,
        via=via,
        http_path=http_path,
    )
    changed = () if dry_run else apply_feature_projection(plan)
    return FeatureProjectionResult(
        feature=plan.feature,
        via=plan.via,
        http_path=plan.http_path,
        changed=changed,
        preserved=plan.binding_plan.preserved,
    )


def feature_projection_digest(plan: FeatureProjectionPlan) -> str:
    """Identify the resolved public route contract recorded by a recipe."""
    payload = {
        "version": FEATURE_PROJECTION_VERSION,
        "feature": plan.feature.to_dict(),
        "via": plan.via,
        "http_path": plan.http_path,
        "bindings": [
            {
                "feature": options.feature,
                "name": options.public_name,
                "path": options.http_path,
                "method": options.method,
                "status_code": options.status_code,
            }
            for options in plan.binding_plan.options
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_crud_application_contract(
    project_dir: Path,
    paths: ProjectPaths,
    manifest: FeatureManifest,
) -> None:
    entities = [
        entity
        for entity in scan_entities(project_dir)
        if entity.pascal == manifest.entity.name
    ]
    if len(entities) != 1:
        raise ValueError(
            "Feature manifest entity does not resolve to one project domain model"
        )
    expected_module = paths.import_path("domain", "models", entities[0].file_path.stem)
    if manifest.entity.module != expected_module:
        raise ValueError(
            "Feature manifest entity module does not match the project domain model"
        )

    errors_path = paths.package_root / "domain" / "errors" / f"{manifest.feature}.py"
    error_names = {
        f"{manifest.entity.name}NotFoundError",
        f"{manifest.entity.name}VersionConflictError",
    }
    if not error_names <= _class_names(errors_path):
        raise ValueError("CRUD feature errors no longer match their blueprint contract")

    container_path = paths.containers / f"{manifest.feature}.py"
    tree = _python_tree(container_path, "CRUD feature container")
    builder = f"build_{manifest.feature}_use_cases"
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == builder
    ]
    if len(functions) != 1 or not isinstance(functions[0].returns, ast.Name):
        raise ValueError(
            "CRUD feature container no longer matches its blueprint contract"
        )
    result_type = functions[0].returns.id
    result_models = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == result_type
    ]
    fields = (
        {
            node.target.id
            for node in result_models[0].body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        if len(result_models) == 1
        else set()
    )
    if not set(manifest.operations) <= fields:
        raise ValueError(
            "CRUD feature container no longer matches its blueprint contract"
        )


def _class_names(path: Path) -> set[str]:
    tree = _python_tree(path, "CRUD feature errors")
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _python_tree(path: Path, label: str) -> ast.Module:
    if not path.is_file():
        raise ValueError(f"{label} not found: {path}")
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _collection_path(raw: str | None, feature: str) -> str:
    path = raw or f"/v1/{feature.replace('_', '-')}"
    if path.endswith("/"):
        raise ValueError("Feature collection path must not end with /")
    if http_path_parameters(path):
        raise ValueError("Feature collection path must not contain path parameters")
    return path


def _crud_fastapi_requests(
    manifest: FeatureManifest,
    *,
    collection_path: str,
    container_module: str,
    not_found: ApplicationErrorMapping,
    version_conflict: ApplicationErrorMapping,
) -> tuple[BindingRequest, ...]:
    operation_contracts = (
        ("create", "POST", collection_path, 201, ()),
        ("get", "GET", f"{collection_path}/{{uuid}}", 200, (not_found,)),
        ("list", "GET", collection_path, 200, ()),
        (
            "update",
            "PATCH",
            f"{collection_path}/{{uuid}}",
            200,
            (not_found, version_conflict),
        ),
        ("delete", "DELETE", f"{collection_path}/{{uuid}}", 200, (not_found,)),
    )
    return tuple(
        BindingRequest(
            usecase=f"{operation}_{manifest.feature}",
            via="fastapi",
            feature=manifest.feature,
            public_name=f"{operation}_{manifest.feature}",
            http_path=path,
            method=method,
            status_code=status_code,
            command_type=None,
            container=BindingContainer(
                module=container_module,
                builder=f"build_{manifest.feature}_use_cases",
                attribute=operation,
            ),
            error_mappings=errors,
        )
        for operation, method, path, status_code, errors in operation_contracts
    )
