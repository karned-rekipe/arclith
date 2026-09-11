"""Validation and loading for generated use-case binding manifests."""

from __future__ import annotations

import json
import keyword
from pathlib import Path

from arclith_cli.adapter_blueprints import BLUEPRINT_VERSION
from arclith_cli.binding_options import validate_response_status
from arclith_cli.binding_rendering import BindingOptions


def load_manifest(
    path: Path,
    via: str,
    adapter_import: str,
    port_import: str,
) -> list[dict]:
    manifest = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"version": BLUEPRINT_VERSION, "bindings": []}
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != BLUEPRINT_VERSION
        or not isinstance(manifest.get("bindings"), list)
    ):
        raise ValueError("Unsupported or invalid binding manifest")
    entries = manifest["bindings"]
    _validate_manifest_entries(entries, via, adapter_import, port_import)
    return entries


def _validate_manifest_entries(
    entries: list[dict],
    via: str,
    adapter_import: str,
    port_import: str,
) -> None:
    seen: set[str] = set()
    for entry in entries:
        _validate_manifest_entry(entry, via, adapter_import, port_import)
        if entry["usecase"] in seen:
            raise ValueError("Duplicate use case in binding manifest")
        seen.add(entry["usecase"])


def _validate_manifest_entry(
    entry: dict,
    via: str,
    adapter_import: str,
    port_import: str,
) -> None:
    keys = {
        "usecase",
        "port_module",
        "port",
        "binding_module",
        "options",
        "factory",
    }
    if not isinstance(entry, dict) or set(entry) != keys:
        raise ValueError("Invalid binding manifest entry")
    _validate_manifest_options(entry["options"], via)
    for key in ("usecase", "port"):
        _validate_python_name(entry[key], module=False)
    for key in ("port_module", "binding_module"):
        _validate_python_name(entry[key], module=True)
    if not entry["binding_module"].startswith(adapter_import + "."):
        raise ValueError("Binding manifest module belongs to another adapter")
    if not entry["port_module"].startswith(port_import + "."):
        raise ValueError(
            "Binding manifest port belongs outside the application inbound ports"
        )
    package = port_import.split(".domain.ports.inbound", 1)[0]
    _validate_factory(entry["factory"], package)


def _validate_factory(factory: object, package: str) -> None:
    keys = {
        "module",
        "class",
        "repository_entity_module",
        "repository_entity",
    }
    if not isinstance(factory, dict) or set(factory) != keys:
        raise ValueError("Invalid binding manifest factory")
    module = factory["module"]
    implementation = factory["class"]
    if (module is None) != (implementation is None):
        raise ValueError("Invalid binding manifest implementation factory")
    if module is not None:
        _validate_python_name(module, module=True)
        _validate_python_name(implementation, module=False)
    if module is not None and not module.startswith(
        package + ".application.use_cases."
    ):
        raise ValueError("Binding factory belongs outside application use cases")
    entity_module = factory["repository_entity_module"]
    entity = factory["repository_entity"]
    if (entity_module is None) != (entity is None):
        raise ValueError("Invalid binding manifest repository factory")
    if entity_module is not None:
        _validate_python_name(entity_module, module=True)
        _validate_python_name(entity, module=False)
        if not entity_module.startswith(package + ".domain.models."):
            raise ValueError("Binding entity belongs outside domain models")


def _validate_manifest_options(options: dict, via: str) -> None:
    if not isinstance(options, dict) or set(options) != set(
        BindingOptions.__dataclass_fields__
    ):
        raise ValueError("Invalid binding manifest options")
    if options["via"] != via:
        raise ValueError("Invalid binding manifest transport")
    try:
        validate_response_status(options["status_code"])
    except ValueError as exc:
        raise ValueError(f"Invalid binding manifest status_code: {exc}") from exc
    if any(
        not isinstance(value, str)
        for name, value in options.items()
        if name != "status_code"
    ):
        raise ValueError("Invalid manifest option value")


def _validate_python_name(value: str, *, module: bool) -> None:
    if not isinstance(value, str):
        raise ValueError("Invalid Python name in binding manifest")
    parts = value.split(".") if module else [value]
    if any(
        not part.isidentifier() or keyword.iskeyword(part) or part.startswith("_")
        for part in parts
    ):
        raise ValueError("Invalid Python name in binding manifest")
