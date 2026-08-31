from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from arclith_cli.adapter_templates import render
from arclith_cli.capabilities import SecretMappingSpec

console = Console()
ARCLITH_DEPENDENCY_RE = re.compile(
    r"""(?P<quote>["'])arclith(?:\[(?P<extras>[^]]*)\])?(?P<constraint>[^"']*)(?P=quote)"""
)


def _parse_env_template(rendered: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in rendered.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key:
            values[key] = value
    return values


def _merge_env_file(
    env_path: Path,
    updates: dict[str, str],
    *,
    overwrite_keys: set[str] | None = None,
) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = (
        env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    )
    merged_lines: list[str] = []
    seen: set[str] = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            merged_lines.append(line)
            continue
        key_raw, existing_value = stripped.split("=", 1)
        key = key_raw.strip()
        if key in updates:
            preserve_existing = (
                overwrite_keys is not None
                and key not in overwrite_keys
                and bool(existing_value.strip())
            )
            if preserve_existing or (not updates[key] and existing_value.strip()):
                merged_lines.append(line)
            else:
                merged_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            merged_lines.append(line)

    for key, value in updates.items():
        if key not in seen and value:
            merged_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(merged_lines).rstrip("\n") + "\n", encoding="utf-8")


def _merge_yaml_file(
    path: Path,
    rendered_yaml: str,
    *,
    preserve_existing: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_yaml_mapping(path)
    update = yaml.safe_load(rendered_yaml) or {}
    if not isinstance(update, dict):
        console.print(
            "[red]✗[/red] La configuration YAML générée doit être un mapping."
        )
        raise typer.Exit(1)
    merged = (
        {**update, **existing}
        if preserve_existing
        else _deep_merge_mapping(existing, update)
    )
    path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


_LANGSMITH_PARAMETER_PATHS: dict[str, tuple[str, ...]] = {
    "tracing_enabled": ("tracing", "enabled"),
    "tracing_mode": ("tracing", "mode"),
    "sampling_rate": ("tracing", "sampling_rate"),
    "project": ("project",),
    "endpoint": ("endpoint",),
    "capture_inputs": ("capture", "inputs"),
    "capture_outputs": ("capture", "outputs"),
    "capture_metadata": ("capture", "metadata"),
    "capture_model_content": ("capture", "model_content"),
    "instrument_langgraph": ("instrumentation", "langgraph"),
    "instrument_pydantic_ai": ("instrumentation", "pydantic_ai"),
    "instrument_fastapi": ("instrumentation", "fastapi"),
    "instrument_fastmcp": ("instrumentation", "fastmcp"),
    "instrument_command_bus": ("instrumentation", "command_bus"),
    "diagnostics_enabled": ("diagnostics", "enabled"),
}


def _merge_langsmith_config(
    path: Path,
    rendered_yaml: str,
    *,
    explicit_params: set[str],
) -> None:
    """Fill missing defaults while preserving user values on later CLI runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(rendered_yaml, encoding="utf-8")
        return
    generated = yaml.safe_load(rendered_yaml) or {}
    if not isinstance(generated, dict):
        console.print("[red]✗[/red] La configuration LangSmith doit être un mapping.")
        raise typer.Exit(1)
    existing = read_yaml_mapping(path)
    merged = _deep_merge_mapping(generated, existing)
    for parameter in explicit_params:
        config_path = _LANGSMITH_PARAMETER_PATHS.get(parameter)
        if config_path is not None:
            _copy_nested_value(generated, merged, config_path)
    path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _copy_nested_value(
    source: dict[str, Any],
    destination: dict[str, Any],
    path: tuple[str, ...],
) -> None:
    source_cursor: Any = source
    destination_cursor: dict[str, Any] = destination
    for key in path[:-1]:
        source_cursor = source_cursor[key]
        child = destination_cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            destination_cursor[key] = child
        destination_cursor = child
    destination_cursor[path[-1]] = source_cursor[path[-1]]


def _merge_secrets_file(
    secrets_path: Path,
    mappings: tuple[SecretMappingSpec, ...],
    *,
    resolver: str | None = None,
    config_template: str = "",
    params: dict[str, Any] | None = None,
) -> None:
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    data = read_yaml_mapping(secrets_path)
    existing_resolver = data.get("resolver")
    if resolver is not None:
        data["resolver"] = resolver
    elif not isinstance(existing_resolver, str) or not existing_resolver.strip():
        data["resolver"] = "env"

    render_params = params or {}
    if config_template:
        rendered_config = render(config_template, render_params)
        config_data = yaml.safe_load(rendered_config) or {}
        if not isinstance(config_data, dict):
            console.print(
                "[red]✗[/red] La configuration de secrets générée doit être un mapping YAML."
            )
            raise typer.Exit(1)
        data = _deep_merge_mapping(data, config_data)

    existing_mappings = data.get("mappings")
    if not isinstance(existing_mappings, dict):
        existing_mappings = {}

    merged_mappings = dict(existing_mappings)
    for mapping in mappings:
        field_path = render(mapping.field_path, render_params).strip()
        secret_key = render(mapping.secret_key, render_params).strip()
        if not field_path:
            console.print(
                "[red]✗[/red] Un mapping de secret doit cibler un champ non vide."
            )
            raise typer.Exit(1)
        merged_mappings[field_path] = secret_key
    data["mappings"] = merged_mappings

    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    secrets_path.write_text(rendered, encoding="utf-8")


def _deep_merge_mapping(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge_mapping(current, value)
        else:
            result[key] = value
    return result


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(loaded, dict):
        return dict(loaded)
    return {}


def _ensure_gitignore_entries(project_dir: Path, entries: tuple[str, ...]) -> None:
    gitignore = project_dir / ".gitignore"
    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    existing = {line.strip() for line in lines}
    missing = [entry for entry in entries if entry not in existing]
    if not missing:
        return
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(missing)
    gitignore.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def _ensure_arclith_extra(pyproject: Path, extra: str) -> None:
    if not pyproject.exists():
        return
    text = pyproject.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(?P<quote>["\'])arclith(?:\[(?P<extras>[^]]*)\])?'
        r'(?P<version>\s*(?:[<>=!~@][^"\']*)?)(?P=quote)'
    )
    match = pattern.search(text)
    if match is None:
        return
    extras = [
        item.strip()
        for item in (match.group("extras") or "").split(",")
        if item.strip()
    ]
    if extra in extras:
        return
    extras.append(extra)
    rendered = (
        f"{match.group('quote')}arclith[{','.join(extras)}]"
        f"{match.group('version')}{match.group('quote')}"
    )
    pyproject.write_text(
        text[: match.start()] + rendered + text[match.end() :],
        encoding="utf-8",
    )
