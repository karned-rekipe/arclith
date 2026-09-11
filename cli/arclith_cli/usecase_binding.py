"""Plan and install deterministic, typed use case bindings without overwriting code."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from arclith_cli.adapter_blueprints import BLUEPRINT_VERSION, render_feature_blueprint
from arclith_cli.binding_contract import UseCaseContract, inspect_usecase
from arclith_cli.binding_composition import (
    GENERATED_COMPOSITION_HEADER,
    GENERATED_REGISTRY_HEADER,
    LEGACY_COMPOSITION_HEADER,
    LEGACY_REGISTRY_HEADER,
    render_composition,
    render_registry,
)
from arclith_cli.binding_manifest import load_manifest
from arclith_cli.binding_options import resolve_binding_options
from arclith_cli.binding_rendering import (
    ApplicationErrorMapping,
    BindingOptions,
    native_module,
    render_binding,
    render_contract,
)
from arclith_cli.http_paths import http_path_parameters, http_route_shape
from arclith_cli.project_paths import ProjectPaths, detect_project_paths

TRANSPORTS = ("fastapi", "fastmcp", "langgraph", "rabbitmq")


@dataclass(frozen=True)
class BindingPlan:
    files: dict[Path, str]
    preserved: tuple[Path, ...]
    options: BindingOptions
    project_dir: Path
    originals: dict[Path, bytes | None]


@dataclass(frozen=True)
class BindingContainer:
    module: str
    builder: str
    attribute: str


@dataclass(frozen=True)
class BindingRequest:
    usecase: str
    via: str
    feature: str | None
    public_name: str | None
    http_path: str | None
    method: str | None
    status_code: int
    command_type: str | None
    container: BindingContainer | None
    error_mappings: tuple[ApplicationErrorMapping, ...]


@dataclass(frozen=True)
class BindingBatchPlan:
    files: dict[Path, str]
    preserved: tuple[Path, ...]
    options: tuple[BindingOptions, ...]
    project_dir: Path
    originals: dict[Path, bytes | None]


def plan_binding(
    project_dir: Path,
    usecase: str,
    *,
    via: str,
    feature: str | None = None,
    public_name: str | None = None,
    http_path: str | None = None,
    method: str | None = None,
    status_code: int = 200,
    command_type: str | None = None,
) -> BindingPlan:
    """Validate all choices and collisions before any filesystem mutation."""
    batch = plan_bindings(
        project_dir,
        (
            BindingRequest(
                usecase=usecase,
                via=via,
                feature=feature,
                public_name=public_name,
                http_path=http_path,
                method=method,
                status_code=status_code,
                command_type=command_type,
                container=None,
                error_mappings=(),
            ),
        ),
    )
    return BindingPlan(
        files=batch.files,
        preserved=batch.preserved,
        options=batch.options[0],
        project_dir=batch.project_dir,
        originals=batch.originals,
    )


def plan_bindings(
    project_dir: Path,
    requests: tuple[BindingRequest, ...],
) -> BindingBatchPlan:
    """Preflight multiple bindings against one cumulative manifest before writes."""
    if not requests:
        raise ValueError("At least one binding request is required")
    transports = {request.via for request in requests}
    if len(transports) != 1:
        raise ValueError("A binding batch must target exactly one transport")
    via = requests[0].via
    if via not in TRANSPORTS:
        raise ValueError(f"via must be one of {', '.join(TRANSPORTS)}")
    if not project_dir.is_dir():
        raise ValueError("Project directory does not exist")
    paths = detect_project_paths(project_dir)
    _check_containment(project_dir, (paths.inbound_ports,))
    layer = "bidirectional" if via == "rabbitmq" else "inbound"
    root = paths.package_root / "adapters" / layer / via
    if not root.is_dir():
        raise ValueError(
            f"Install the {via} adapter with add-adapter before exposing its use cases"
        )
    prefix = paths.import_path("adapters", layer, via)
    manifest_path = project_dir / ".arclith/bindings" / f"{via}.json"
    _check_containment(project_dir, (root, manifest_path))
    entries = load_manifest(
        manifest_path, via, prefix, paths.import_path("domain", "ports", "inbound")
    )
    planned: dict[Path, str] = {}
    preserved: set[Path] = set()
    resolved_options: list[BindingOptions] = []
    for request in requests:
        contract = inspect_usecase(paths, request.usecase)
        if contract.requires_container and request.container is None:
            raise ValueError(
                f"Use case {contract.name} requires its application feature container; "
                "use expose-feature"
            )
        if not contract.requires_container and request.container is not None:
            raise ValueError(
                f"Use case {contract.name} does not declare a container-managed dependency"
            )
        options = resolve_binding_options(
            contract,
            via=request.via,
            feature=request.feature,
            public_name=request.public_name,
            http_path=request.http_path,
            method=request.method,
            status_code=request.status_code,
            command_type=request.command_type,
        )
        factory: dict[str, object] = {
            "module": contract.implementation_module,
            "class": contract.implementation,
            "repository_entity_module": contract.repository_entity_module,
            "repository_entity": contract.repository_entity,
        }
        if request.container is not None:
            factory["container"] = asdict(request.container)
        entry = {
            "usecase": contract.name,
            "port_module": contract.module,
            "port": contract.port,
            "binding_module": prefix
            + "."
            + native_module(contract, options).replace("/", "."),
            "options": asdict(options),
            "factory": factory,
        }
        entries = _merge_entry(entries, entry, root, contract, options)
        developer_files, developer_preserved = _developer_files(
            project_dir,
            root,
            contract,
            options,
            prefix,
            paths.package_name or "",
            request.error_mappings,
        )
        _merge_planned_files(planned, developer_files)
        preserved.update(developer_preserved)
        _merge_planned_files(
            planned,
            _contract_test_files(project_dir, via, prefix, contract, options),
        )
        resolved_options.append(options)
    composition_entries = _composition_entries(paths, manifest_path, entries)
    _merge_planned_files(
        planned,
        _generated_files(
            root,
            manifest_path,
            entries,
            via,
            paths.import_path("infrastructure", "use_cases_generated"),
            paths.package_root / "infrastructure" / "use_cases_generated.py",
            composition_entries,
        ),
    )
    planned = _changed_files(planned)
    _check_containment(project_dir, (*planned, *preserved))
    originals = {path: path.read_bytes() if path.exists() else None for path in planned}
    return BindingBatchPlan(
        files=planned,
        preserved=tuple(sorted(preserved)),
        options=tuple(resolved_options),
        project_dir=project_dir,
        originals=originals,
    )


def _merge_planned_files(target: dict[Path, str], source: dict[Path, str]) -> None:
    for path, content in source.items():
        existing = target.get(path)
        if existing is not None and existing != content:
            raise ValueError(f"Binding batch renders conflicting content for {path}")
        target[path] = content


def _changed_files(planned: dict[Path, str]) -> dict[Path, str]:
    return {
        path: content
        for path, content in planned.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    }


def _merge_entry(
    entries: list[dict],
    entry: dict,
    root: Path,
    contract: UseCaseContract,
    options: BindingOptions,
) -> list[dict]:
    registered = next(
        (item for item in entries if item["usecase"] == contract.name),
        None,
    )
    if registered is not None and registered != entry:
        raise ValueError(
            "This use case already has a different binding; preserve and edit "
            "its public contract explicitly"
        )
    _check_collisions(entries, entry)
    operation_files = (
        root / f"contracts/{contract.name}.py",
        root / (native_module(contract, options) + ".py"),
    )
    if registered is None and any(path.exists() for path in operation_files):
        raise ValueError(
            "A developer file already occupies this binding; select a distinct use case name"
        )
    entries = sorted(
        [item for item in entries if item["usecase"] != contract.name] + [entry],
        key=lambda item: item["usecase"],
    )
    return entries


def _developer_files(
    project_dir: Path,
    root: Path,
    contract: UseCaseContract,
    options: BindingOptions,
    prefix: str,
    package: str,
    error_mappings: tuple[ApplicationErrorMapping, ...],
) -> tuple[dict[Path, str], tuple[Path, ...]]:
    via = options.via
    rendered = (
        render_feature_blueprint(via, options.feature, package)
        if via in {"fastapi", "fastmcp"}
        else {}
    )
    rendered.update(
        {
            "contracts/__init__.py": '"""Transport contracts snapshotted from typed application requests."""\n',
            f"contracts/{contract.name}.py": render_contract(
                contract,
                _binding_path_parameters(options),
            ),
            native_module(contract, options) + ".py": render_binding(
                contract,
                options,
                prefix,
                error_mappings,
            ),
        }
    )
    planned = {root / relative: content for relative, content in rendered.items()}
    _ensure_packages(project_dir, root, planned)
    preserved = tuple(sorted(path for path in planned if path.exists()))
    planned = {path: content for path, content in planned.items() if not path.exists()}
    return planned, preserved


def _generated_files(
    root: Path,
    manifest_path: Path,
    entries: list[dict],
    via: str,
    composition_import: str,
    composition_path: Path,
    composition_entries: list[dict],
) -> dict[Path, str]:
    planned: dict[Path, str] = {}
    registry = root / "bindings_generated.py"
    registry_headers = (GENERATED_REGISTRY_HEADER, LEGACY_REGISTRY_HEADER)
    if registry.exists() and not registry.read_text(encoding="utf-8").startswith(
        registry_headers
    ):
        raise ValueError(f"Refusing to replace developer-owned registry {registry}")
    planned[registry] = render_registry(entries, via, composition_import)
    composition_headers = (GENERATED_COMPOSITION_HEADER, LEGACY_COMPOSITION_HEADER)
    if composition_path.exists() and not composition_path.read_text(
        encoding="utf-8"
    ).startswith(composition_headers):
        raise ValueError(
            f"Refusing to replace developer-owned composition {composition_path}"
        )
    planned[composition_path] = render_composition(composition_entries)
    planned[manifest_path] = (
        json.dumps(
            {"version": BLUEPRINT_VERSION, "bindings": entries},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return planned


def _composition_entries(
    paths: ProjectPaths,
    current_manifest: Path,
    current_entries: list[dict],
) -> list[dict]:
    by_usecase = {entry["usecase"]: entry for entry in current_entries}
    manifests = current_manifest.parent
    if not manifests.is_dir():
        return list(by_usecase.values())
    for path in sorted(manifests.glob("*.json")):
        if path == current_manifest or path.stem not in TRANSPORTS:
            continue
        layer = "bidirectional" if path.stem == "rabbitmq" else "inbound"
        prefix = paths.import_path("adapters", layer, path.stem)
        entries = load_manifest(
            path,
            path.stem,
            prefix,
            paths.import_path("domain", "ports", "inbound"),
        )
        for entry in entries:
            existing = by_usecase.get(entry["usecase"])
            if existing is not None and (
                existing["port_module"],
                existing["port"],
                existing["factory"],
            ) != (entry["port_module"], entry["port"], entry["factory"]):
                raise ValueError(
                    "A use case has inconsistent composition across transport manifests"
                )
            by_usecase.setdefault(entry["usecase"], entry)
    return [by_usecase[name] for name in sorted(by_usecase)]


def _contract_test_files(
    project_dir: Path,
    via: str,
    prefix: str,
    contract: UseCaseContract,
    options: BindingOptions,
) -> dict[Path, str]:
    planned: dict[Path, str] = {}
    test_path = (
        project_dir / "tests" / "adapters" / via / f"test_{contract.name}_contract.py"
    )
    if not test_path.exists():
        test_files = {
            test_path: _render_contract_test(
                prefix,
                contract.name,
                contract.module,
                contract.request,
                contract.transport_request,
                _binding_path_parameters(options),
            )
        }
        _ensure_packages(project_dir, project_dir / "tests", test_files)
        planned.update(test_files)
    return planned


def _render_contract_test(
    adapter_import: str,
    name: str,
    module: str,
    request: str,
    transport: str,
    path_parameters: tuple[str, ...],
) -> str:
    path_parameter_assertions = "".join(
        f'    application["properties"].pop({parameter!r})\n'
        for parameter in path_parameters
    )
    if path_parameters:
        path_parameter_assertions += (
            f"    path_parameters = {path_parameters!r}\n"
            '    application["required"] = [\n'
            '        field for field in application.get("required", [])\n'
            "        if field not in path_parameters\n"
            "    ]\n"
            '    if not application["required"]:\n'
            '        application.pop("required", None)\n'
        )
    return (
        '"""Detect application input drift after the initial transport snapshot.\n\n'
        "When intentionally versioning a transport, replace this guard with examples\n"
        'covering the explicit migration mapper.\n"""\n\n'
        f"from {module} import (\n    {request},\n)\n"
        f"from {adapter_import}.contracts.{name} import (\n    {transport},\n)\n\n\n"
        f"def test_{name}_input_contract_has_not_drifted() -> None:\n"
        f"    application = {request}.model_json_schema(by_alias=False)\n"
        f"    transport = {transport}.model_json_schema(by_alias=False)\n"
        + path_parameter_assertions
        + '    application.pop("title", None)\n'
        '    transport.pop("title", None)\n'
        "    assert transport == application\n"
    )


def _binding_path_parameters(options: BindingOptions) -> tuple[str, ...]:
    return http_path_parameters(options.http_path) if options.via == "fastapi" else ()


def apply_binding(plan: BindingPlan | BindingBatchPlan) -> tuple[Path, ...]:
    _check_containment(plan.project_dir, (*plan.files, *plan.preserved))
    for path, original in plan.originals.items():
        current = path.read_bytes() if path.is_file() else None
        if current != original or (path.exists() and not path.is_file()):
            raise ValueError(
                f"File changed after binding planning; rerun the command: {path}"
            )
    for path, content in plan.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tuple(plan.files)


def _check_collisions(entries: list[dict], entry: dict) -> None:
    for current in entries:
        if current["usecase"] == entry["usecase"]:
            continue
        options = entry["options"]
        previous = current["options"]
        keys = (
            ("public_name", "command_type")
            if options["via"] == "rabbitmq"
            else ("public_name",)
        )
        if any(options[key] == previous[key] for key in keys):
            raise ValueError(
                "A binding already owns this public component name or command type"
            )
        if options["via"] == "fastapi" and (
            http_route_shape(options["http_path"]),
            options["method"],
        ) == (http_route_shape(previous["http_path"]), previous["method"]):
            raise ValueError("A binding already owns this HTTP method and path shape")


def _ensure_packages(project_dir: Path, root: Path, planned: dict[Path, str]) -> None:
    for path in list(planned):
        for parent in path.parents:
            if parent == root.parent or parent == project_dir:
                break
            init = parent / "__init__.py"
            if not init.exists():
                planned.setdefault(
                    init,
                    '"""Explicit adapter package; no import-time registrations."""\n',
                )


def _check_containment(project_dir: Path, paths: tuple[Path, ...]) -> None:
    resolved = project_dir.resolve()
    for path in paths:
        if not path.resolve().is_relative_to(resolved):
            raise ValueError(f"Binding path escapes the project: {path}")
