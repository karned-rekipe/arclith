from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from arclith_cli.adapter_config import (
    _ensure_arclith_extra,
    _ensure_gitignore_entries,
    _merge_env_file,
    _merge_langsmith_config,
    _merge_secrets_file,
    _merge_yaml_file,
    _parse_env_template,
    read_yaml_mapping,
)
from arclith_cli.adapter_blueprints import (
    assert_no_module_shadowing,
    get_adapter_blueprint,
    scaffold_adapter_blueprint,
)
from arclith_cli.adapter_rendering import (
    _configured_agent_persistence_extras,
    _ensure_arclith_extras,
    _file_template_vars,
)
from arclith_cli.adapter_templates import render
from arclith_cli.capabilities import AdapterSpec, CapabilitySpec
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import detect_project_paths

console = Console()
_LANGSMITH_ENV_PARAMETERS: dict[str, str] = {
    "LANGSMITH_TRACING": "tracing_enabled",
    "LANGSMITH_PROJECT": "project",
    "LANGSMITH_ENDPOINT": "endpoint",
    "LANGSMITH_TRACING_MODE": "tracing_mode",
    "LANGSMITH_TRACING_SAMPLING_RATE": "sampling_rate",
    "LANGSMITH_HIDE_INPUTS": "capture_inputs",
    "LANGSMITH_HIDE_OUTPUTS": "capture_outputs",
    "LANGSMITH_HIDE_METADATA": "capture_metadata",
}


@dataclass(frozen=True)
class GenerationRequest:
    project_dir: Path
    capability: CapabilitySpec
    adapter: AdapterSpec
    entities: list[EntityInfo]
    params: dict[str, Any]
    activate: bool
    explicit_params: set[str]


def _generate(request: GenerationRequest) -> None:
    paths = detect_project_paths(request.project_dir)
    blueprint = get_adapter_blueprint(request.adapter)
    assert_no_module_shadowing(
        paths.package_root.joinpath(*blueprint.root_parts), blueprint
    )
    request = replace(
        request,
        params={
            **request.params,
            **_file_template_vars(
                request.project_dir,
                paths,
                request.adapter,
                params=request.params,
            ),
        },
    )

    _write_primary_config(request)
    _ensure_adapter_dependency(request)
    _write_merged_configs(request)
    _write_environment(request)
    _write_secrets(request)
    _write_gitignore(request)
    for generated in scaffold_adapter_blueprint(
        request.project_dir,
        paths,
        request.adapter,
        graph_name=str(request.params.get("graph_name", "agent")),
    ):
        console.print(f"[green]✓[/green] {generated.relative_to(request.project_dir)}")
    _write_static_templates(request)
    _activate_adapter(request)
    _ensure_persistence_dependencies(request)
    console.print(
        f"\n[bold green]✓ Adapter [cyan]{request.adapter.name}[/cyan] scaffoldé avec succès.[/bold green]"
    )


def _write_primary_config(request: GenerationRequest) -> None:
    adapter = request.adapter
    if not (adapter.has_config() and adapter.config_path):
        return

    config_path = request.project_dir / adapter.config_path
    rendered = render(adapter.config_template, request.params)
    if adapter.capability == "observability" and adapter.name == "langsmith":
        _merge_langsmith_config(
            config_path,
            rendered,
            explicit_params=request.explicit_params,
        )
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(rendered, encoding="utf-8")
    console.print(f"[green]✓[/green] {config_path.relative_to(request.project_dir)}")


def _ensure_adapter_dependency(request: GenerationRequest) -> None:
    extra = request.adapter.dependency_extra
    if not extra:
        return
    _ensure_arclith_extra(request.project_dir / "pyproject.toml", extra)
    console.print(f"[cyan]↺[/cyan] pyproject.toml → arclith[{extra}]")


def _write_merged_configs(request: GenerationRequest) -> None:
    for template in request.adapter.merge_config_templates:
        config_path = request.project_dir / render(template.path, request.params)
        _merge_yaml_file(
            config_path,
            render(template.template, request.params),
            preserve_existing=template.preserve_existing,
        )
        console.print(
            f"[green]✓[/green] {config_path.relative_to(request.project_dir)}"
        )


def _write_environment(request: GenerationRequest) -> None:
    adapter = request.adapter
    if not (adapter.has_env() and adapter.env_path):
        return

    overrides = _langsmith_environment_overrides(request)
    env_path = request.project_dir / adapter.env_path
    _merge_env_file(
        env_path,
        _parse_env_template(render(adapter.env_template, request.params)),
        overwrite_keys=overrides,
    )
    _ensure_gitignore_entries(request.project_dir, (".env",))
    console.print(f"[green]✓[/green] {env_path.relative_to(request.project_dir)}")


def _langsmith_environment_overrides(
    request: GenerationRequest,
) -> set[str] | None:
    adapter = request.adapter
    if not (adapter.capability == "observability" and adapter.name == "langsmith"):
        return None
    return {
        env_name
        for env_name, parameter in _LANGSMITH_ENV_PARAMETERS.items()
        if parameter in request.explicit_params
    }


def _write_secrets(request: GenerationRequest) -> None:
    adapter = request.adapter
    if not (adapter.has_secret_mappings() or adapter.has_secret_config()):
        return

    secrets_path = request.project_dir / "config" / "secrets.yaml"
    _merge_secrets_file(
        secrets_path,
        adapter.secret_mappings,
        resolver=adapter.secret_resolver,
        config_template=adapter.secret_config_template,
        params=request.params,
    )
    console.print(f"[green]✓[/green] {secrets_path.relative_to(request.project_dir)}")


def _write_gitignore(request: GenerationRequest) -> None:
    if not request.adapter.gitignore_entries:
        return
    _ensure_gitignore_entries(request.project_dir, request.adapter.gitignore_entries)
    console.print("[green]✓[/green] .gitignore")


def _write_static_templates(request: GenerationRequest) -> None:
    for template in request.adapter.file_templates:
        generated_path = request.project_dir / render(template.path, request.params)
        if generated_path.exists():
            console.print(
                f"[cyan]préservé[/cyan] {generated_path.relative_to(request.project_dir)}"
            )
            continue
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(
            render(template.template, request.params),
            encoding="utf-8",
        )
        if generated_path.name == "arclith-run":
            generated_path.chmod(0o755)
        console.print(
            f"[green]✓[/green] {generated_path.relative_to(request.project_dir)}"
        )


def _activate_adapter(request: GenerationRequest) -> None:
    if request.activate:
        _update_active_capability(
            request.project_dir,
            request.capability,
            request.adapter,
        )


def _ensure_persistence_dependencies(request: GenerationRequest) -> None:
    if request.adapter.capability != "agent-persistence":
        return
    extras = _configured_agent_persistence_extras(
        request.project_dir,
        request.params,
    )
    _ensure_arclith_extras(request.project_dir, extras)


def _update_active_capability(
    project_dir: Path, capability: CapabilitySpec, adapter: AdapterSpec
) -> None:
    if capability.activation_config_key is None:
        return
    if capability.name == "observability":
        _enable_observability_adapter(project_dir, adapter)
        return

    cfg = project_dir / "config" / "adapters" / "adapters.yaml"
    key = capability.activation_config_key
    escaped_key = re.escape(key)
    if not cfg.exists():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f"{key}: {adapter.name}\n", encoding="utf-8")
    else:
        text = cfg.read_text(encoding="utf-8")
        if re.search(rf"(?m)^{escaped_key}:", text):
            text = re.sub(
                rf"(?m)^({escaped_key}:\s*).*$", rf"\g<1>{adapter.name}", text
            )
        else:
            text = text.rstrip("\n") + f"\n{key}: {adapter.name}\n"
        cfg.write_text(text, encoding="utf-8")
    console.print(
        f"[cyan]↺[/cyan] config/adapters/adapters.yaml → {key}: {adapter.name}"
    )


def _enable_observability_adapter(project_dir: Path, adapter: AdapterSpec) -> None:
    cfg = project_dir / "config" / "adapters" / "adapters.yaml"
    data = read_yaml_mapping(cfg)
    existing = data.get("observability")
    if isinstance(existing, dict) and isinstance(existing.get("enabled"), list):
        enabled = []
        for name in existing["enabled"]:
            if isinstance(name, str) and name not in enabled:
                enabled.append(name)
    else:
        enabled = []

    if adapter.name not in enabled:
        enabled.append(adapter.name)

    data["observability"] = {"enabled": enabled}
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    console.print(
        f"[cyan]↺[/cyan] config/adapters/adapters.yaml → observability.enabled += {adapter.name}"
    )
