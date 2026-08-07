from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .adapter_templates import (
    REPO_PYTHON,
    REPO_REEXPORT,
    render,
    render_container,
)
from .capabilities import (
    AdapterSpec,
    CapabilitySpec,
    ParameterSpec,
    SecretMappingSpec,
    capability_names,
    get_capability,
)
from .entity_scanner import EntityInfo, scan_entities, scan_installed_adapters
from .project_paths import ProjectPaths, detect_project_paths

console = Console()


# ── Entry point ───────────────────────────────────────────────────────────────

def add_adapter_cmd(
    *,
    project_dir: Path | None = None,
    capability_name: str = "repository",
    adapter: str | None = None,
    entity_names: list[str] | None = None,
    all_entities: bool = False,
    activate: bool = True,
    db_name: str | None = None,
    multitenant: bool | None = None,
    duckdb_path: str | None = None,
    adapter_params: dict[str, str] | None = None,
    yes: bool = False,
) -> None:
    """Wizard interactif pour scaffolder un adapter du catalogue."""
    project_dir = project_dir or Path.cwd()

    _assert_arclith_project(project_dir)

    capability = _resolve_capability(capability_name)
    adapter_spec = _resolve_adapter_type(capability, adapter)
    adapter = adapter_spec.name
    entities = _resolve_entities(project_dir, entity_names, all_entities, yes=yes, adapter=adapter_spec)
    params = _resolve_adapter_params(
        adapter_spec,
        project_dir,
        db_name=db_name,
        multitenant=multitenant,
        duckdb_path=duckdb_path,
        extra_params=adapter_params or {},
        prompt_missing=not yes,
    )
    if capability.activation_config_key is None:
        activate = False
    elif not yes:
        activate = Confirm.ask(
            f"\n  [bold]Activer[/bold] [green]{adapter}[/green] maintenant ?",
            default=activate,
        )

    _show_recap(project_dir, capability, adapter_spec, entities, params, activate)

    if not yes and not Confirm.ask("\n  [bold]Confirmer la génération ?[/bold]", default=True):
        console.print("[yellow]Annulé.[/yellow]")
        raise typer.Exit(0)

    _generate(project_dir, capability, adapter_spec, entities, params, activate)


# ── Validation ────────────────────────────────────────────────────────────────

def _assert_arclith_project(project_dir: Path) -> None:
    paths = detect_project_paths(project_dir)
    if not paths.domain_models.exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]domain/models[/bold] ou [bold]src/<package>/domain/models[/bold] trouvé.\n"
            "    Exécutez [bold]arclith-cli add-adapter[/bold] depuis la racine d'un projet arclith."
        )
        raise typer.Exit(1)
    if not (project_dir / "config" / "adapters").exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]config/adapters/[/bold] trouvé.\n"
            "    Le projet doit utiliser la structure [bold]config/[/bold] directory."
        )
        raise typer.Exit(1)


# ── Step 1 : adapter type ─────────────────────────────────────────────────────

def _resolve_capability(capability_name: str) -> CapabilitySpec:
    capability = get_capability(capability_name)
    if capability is not None:
        return capability

    supported = ", ".join(capability_names())
    console.print(f"[red]✗[/red] Capacité inconnue: [bold]{capability_name}[/bold]. Valeurs: {supported}.")
    raise typer.Exit(1)


def _prompt_adapter_type(capability: CapabilitySpec) -> AdapterSpec:
    console.print("\n[bold]① Type d'adapter[/bold]")
    adapter_names = capability.adapter_names()
    for i, name in enumerate(adapter_names, 1):
        console.print(f"   [bold cyan]{i}[/bold cyan]  {name}")

    while True:
        raw = Prompt.ask("\n  Votre choix [dim](numéro ou nom)[/dim]").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(adapter_names):
                selected = capability.get_adapter(adapter_names[idx])
                if selected is not None:
                    return selected
        else:
            selected = capability.get_adapter(raw)
            if selected is not None:
                return selected
        console.print(f"  [red]Choix invalide.[/red] Entrez 1-{len(adapter_names)} ou le nom.")


def _resolve_adapter_type(capability: CapabilitySpec, adapter: str | None) -> AdapterSpec:
    if adapter is None:
        return _prompt_adapter_type(capability)

    selected = capability.get_adapter(adapter)
    if selected is not None:
        return selected

    supported = ", ".join(capability.adapter_names())
    console.print(f"[red]✗[/red] Adapter inconnu: [bold]{adapter}[/bold]. Valeurs: {supported}.")
    raise typer.Exit(1)


# ── Step 2 : entity selection ─────────────────────────────────────────────────

def _prompt_entities(project_dir: Path) -> list[EntityInfo]:
    entities = scan_entities(project_dir)
    if not entities:
        console.print("[red]✗[/red] Aucune entité trouvée dans [bold]src/<package>/domain/models/[/bold].")
        raise typer.Exit(1)

    console.print("\n[bold]② Entité(s) cible(s)[/bold]")
    for i, e in enumerate(entities, 1):
        console.print(f"   [bold cyan]{i}[/bold cyan]  {e.pascal} [dim]({e.snake})[/dim]")
    console.print(f"   [bold cyan]{len(entities) + 1}[/bold cyan]  [italic]toutes[/italic]")

    while True:
        raw = Prompt.ask("\n  Votre choix [dim](numéro(s) séparés par virgule, ou nom)[/dim]").strip()
        selected = _parse_entity_choice(raw, entities)
        if selected is not None:
            return selected
        console.print("  [red]Choix invalide.[/red]")


def _resolve_entities(
    project_dir: Path,
    entity_names: list[str] | None,
    all_entities: bool,
    *,
    yes: bool,
    adapter: AdapterSpec,
) -> list[EntityInfo]:
    if not adapter.entity_scoped:
        if all_entities or entity_names:
            console.print(
                f"[red]✗[/red] L'adapter [bold]{adapter.name}[/bold] n'est pas lié aux entités. "
                "Retirez [bold]--entity[/bold] et [bold]--all-entities[/bold]."
            )
            raise typer.Exit(1)
        return []

    entities = scan_entities(project_dir)
    if not entities:
        console.print("[red]✗[/red] Aucune entité trouvée dans [bold]src/<package>/domain/models/[/bold].")
        raise typer.Exit(1)

    if all_entities:
        return list(entities)

    if entity_names:
        selected = _parse_entity_choice(",".join(entity_names), entities)
        if selected is not None:
            return selected
        allowed = ", ".join(e.pascal for e in entities)
        console.print(f"[red]✗[/red] Entité inconnue. Valeurs: {allowed}.")
        raise typer.Exit(1)

    if len(entities) == 1:
        return [entities[0]]

    if yes:
        console.print(
            "[red]✗[/red] Plusieurs entités détectées. Utilisez [bold]--entity[/bold] ou [bold]--all-entities[/bold]."
        )
        raise typer.Exit(1)

    return _prompt_entities(project_dir)


def _parse_entity_choice(raw: str, entities: list[EntityInfo]) -> list[EntityInfo] | None:
    all_idx = len(entities) + 1
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    result: list[EntityInfo] = []
    for part in parts:
        if part.isdigit():
            idx = int(part)
            if idx == all_idx:
                return list(entities)
            if 1 <= idx <= len(entities):
                e = entities[idx - 1]
                if e not in result:
                    result.append(e)
            else:
                return None
        else:
            matched = [e for e in entities if e.pascal == part or e.snake == part]
            if not matched:
                return None
            for e in matched:
                if e not in result:
                    result.append(e)
    return result or None


# ── Step 3 : adapter-specific params ─────────────────────────────────────────

def _resolve_adapter_params(
    adapter: AdapterSpec,
    project_dir: Path,
    *,
    db_name: str | None,
    multitenant: bool | None,
    duckdb_path: str | None,
    extra_params: dict[str, str],
    prompt_missing: bool,
) -> dict[str, Any]:
    if prompt_missing:
        console.print(f"\n[bold]③ Paramètres [green]{adapter.name}[/green][/bold]")

    _assert_supported_params(adapter, extra_params)

    if not adapter.parameters:
        if prompt_missing:
            console.print("  [dim](aucun paramètre requis)[/dim]")
        return {}

    provided_values: dict[str, str | bool | None] = dict(extra_params)
    convenience_values: dict[str, str | bool | None] = {
        "db_name": db_name,
        "multitenant": multitenant,
        "path": duckdb_path,
    }
    for name, value in convenience_values.items():
        if value is not None:
            provided_values[name] = value

    resolved: dict[str, Any] = {}
    for parameter in adapter.parameters:
        value = _resolve_parameter(parameter, provided_values.get(parameter.name), project_dir, prompt_missing)
        resolved[parameter.name] = _render_parameter_value(parameter, value)

    return resolved


def _assert_supported_params(adapter: AdapterSpec, extra_params: dict[str, str]) -> None:
    supported = {parameter.name for parameter in adapter.parameters}
    unknown = sorted(name for name in extra_params if name not in supported)
    if not unknown:
        return

    allowed = ", ".join(sorted(supported)) or "(aucun)"
    received = ", ".join(unknown)
    console.print(
        f"[red]✗[/red] Paramètre inconnu pour [bold]{adapter.name}[/bold]: {received}. "
        f"Valeurs: {allowed}."
    )
    raise typer.Exit(1)


def _resolve_parameter(
    parameter: ParameterSpec,
    provided_value: str | bool | None,
    project_dir: Path,
    prompt_missing: bool,
) -> str | bool:
    if parameter.kind == "boolean":
        if isinstance(provided_value, bool):
            return provided_value
        if isinstance(provided_value, str) and provided_value.strip():
            parsed = _parse_boolean_param(provided_value)
            if parsed is not None:
                return parsed
            console.print(
                f"[red]✗[/red] Valeur booléenne invalide pour [bold]{parameter.name}[/bold]: "
                f"{provided_value}. Utilisez true/false."
            )
            raise typer.Exit(1)
        boolean_default = _boolean_default(parameter)
        if prompt_missing:
            return Confirm.ask(f"  {parameter.prompt}", default=boolean_default)
        return boolean_default

    resolved = provided_value.strip() if isinstance(provided_value, str) else ""
    string_default = _default_string_value(parameter, project_dir)
    if not resolved and prompt_missing:
        resolved = Prompt.ask(f"  {parameter.prompt}", default=string_default, password=parameter.secret).strip()
    return resolved or string_default


def _default_string_value(parameter: ParameterSpec, project_dir: Path) -> str:
    if parameter.default_from_project_name:
        return project_dir.name
    if isinstance(parameter.default, str):
        return parameter.default
    return ""


def _boolean_default(parameter: ParameterSpec) -> bool:
    if isinstance(parameter.default, bool):
        return parameter.default
    if isinstance(parameter.default, str):
        parsed = _parse_boolean_param(parameter.default)
        if parsed is not None:
            return parsed
    return False


def _parse_boolean_param(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _render_parameter_value(parameter: ParameterSpec, value: str | bool) -> str:
    if parameter.kind == "boolean":
        return _yaml_bool(bool(value))
    if isinstance(value, str):
        return value
    return str(value)


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


# ── Step 4 : recap ────────────────────────────────────────────────────────────

def _show_recap(
    project_dir: Path,
    capability: CapabilitySpec,
    adapter: AdapterSpec,
    entities: list[EntityInfo],
    params: dict[str, Any],
    activate: bool,
) -> None:
    paths = detect_project_paths(project_dir)
    files = _list_generated_files(project_dir, paths, adapter, entities)

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Fichier")
    table.add_column("Action", style="dim")

    for path, action in files:
        style = "yellow" if action == "remplacé ⚠" else "green"
        table.add_row(str(path.relative_to(project_dir)), f"[{style}]{action}[/{style}]")

    if activate and capability.activation_config_key is not None:
        cfg_path = project_dir / "config" / "adapters" / "adapters.yaml"
        table.add_row(
            str(cfg_path.relative_to(project_dir)),
            f"[cyan]mis à jour ({_activation_config_label(capability)})[/cyan]",
        )

    console.print()
    console.print(Panel(table, title=f"[bold]Récapitulatif — adapter [green]{adapter.name}[/green][/bold]"))


def _list_generated_files(
    project_dir: Path,
    paths: ProjectPaths,
    adapter: AdapterSpec,
    entities: list[EntityInfo],
) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []

    if adapter.has_config() and adapter.config_path:
        cfg = project_dir / adapter.config_path
        files.append((cfg, "remplacé ⚠" if cfg.exists() else "créé"))

    if adapter.has_env() and adapter.env_path:
        env_file = project_dir / adapter.env_path
        files.append((env_file, "mis à jour" if env_file.exists() else "créé"))
        gitignore = project_dir / ".gitignore"
        files.append((gitignore, "mis à jour" if gitignore.exists() else "créé"))

    if adapter.has_secret_mappings():
        secrets_file = project_dir / "config" / "secrets.yaml"
        files.append((secrets_file, "mis à jour" if secrets_file.exists() else "créé"))

    template_vars = _file_template_vars(project_dir, paths, adapter, params={})
    for file_template in adapter.file_templates:
        path = project_dir / render(file_template.path, template_vars)
        files.append((path, "remplacé ⚠" if path.exists() else "créé"))

    for entity in entities:
        base = paths.adapters_outbound / adapter.name
        repo_dir = base / "repositories"
        repo_file = repo_dir / f"{entity.snake}_repository.py"
        reexport = base / "repository.py"
        init = base / "__init__.py"
        container = paths.containers / f"{entity.snake}_container.py"

        files.append((init, "remplacé ⚠" if init.exists() else "créé"))
        files.append((repo_file, "remplacé ⚠" if repo_file.exists() else "créé"))
        files.append((reexport, "remplacé ⚠" if reexport.exists() else "créé"))
        files.append((container, "remplacé ⚠" if container.exists() else "créé"))

    return files


def _activation_config_label(capability: CapabilitySpec) -> str:
    if capability.name == "observability":
        return "observability.enabled"
    return capability.activation_config_key or ""


# ── Step 5 : generate ─────────────────────────────────────────────────────────

def _generate(
    project_dir: Path,
    capability: CapabilitySpec,
    adapter: AdapterSpec,
    entities: list[EntityInfo],
    params: dict[str, Any],
    activate: bool,
) -> None:
    installed = scan_installed_adapters(project_dir)
    paths = detect_project_paths(project_dir)
    if adapter.name not in installed:
        installed = sorted(installed + [adapter.name])

    params = {**params, **_file_template_vars(project_dir, paths, adapter, params=params)}

    if adapter.has_config() and adapter.config_path:
        cfg_path = project_dir / adapter.config_path
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(render(adapter.config_template, params), encoding="utf-8")
        console.print(f"[green]✓[/green] {cfg_path.relative_to(project_dir)}")

    if adapter.has_env() and adapter.env_path:
        env_path = project_dir / adapter.env_path
        _merge_env_file(env_path, _parse_env_template(render(adapter.env_template, params)))
        _ensure_env_is_ignored(project_dir)
        console.print(f"[green]✓[/green] {env_path.relative_to(project_dir)}")

    if adapter.has_secret_mappings():
        secrets_path = project_dir / "config" / "secrets.yaml"
        _merge_secrets_file(secrets_path, adapter.secret_mappings)
        console.print(f"[green]✓[/green] {secrets_path.relative_to(project_dir)}")

    for file_template in adapter.file_templates:
        generated_path = project_dir / render(file_template.path, params)
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(render(file_template.template, params), encoding="utf-8")
        console.print(f"[green]✓[/green] {generated_path.relative_to(project_dir)}")

    import_vars = _import_vars(paths)
    for entity in entities:
        vars = {"pascal": entity.pascal, "snake": entity.snake, **params, **import_vars}
        base = paths.adapters_outbound / adapter.name
        repo_dir = base / "repositories"
        repo_dir.mkdir(parents=True, exist_ok=True)

        # __init__.py
        init_file = base / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
        # repositories/__init__.py
        repo_init_file = repo_dir / "__init__.py"
        if not repo_init_file.exists():
            repo_init_file.write_text("", encoding="utf-8")
            console.print(f"[green]✓[/green] {repo_init_file.relative_to(project_dir)}")

        # Repository subclass
        repo_file = repo_dir / f"{entity.snake}_repository.py"
        repo_file.write_text(render(REPO_PYTHON[adapter.name], vars), encoding="utf-8")
        console.print(f"[green]✓[/green] {repo_file.relative_to(project_dir)}")

        # Re-export
        reexport = base / "repository.py"
        reexport.write_text(render(REPO_REEXPORT[adapter.name], vars), encoding="utf-8")
        console.print(f"[green]✓[/green] {reexport.relative_to(project_dir)}")

        # Container (full regeneration)
        container = paths.containers / f"{entity.snake}_container.py"
        existed = container.exists()
        container.parent.mkdir(parents=True, exist_ok=True)
        container.write_text(render_container(entity.pascal, entity.snake, installed, import_vars), encoding="utf-8")
        action = "[yellow]remplacé ⚠[/yellow]" if existed else "[green]créé[/green]"
        console.print(f"{action} {container.relative_to(project_dir)}")

    # Activate selector-based capabilities in config/adapters/adapters.yaml.
    if activate:
        _update_active_capability(project_dir, capability, adapter)

    console.print(f"\n[bold green]✓ Adapter [cyan]{adapter.name}[/cyan] scaffoldé avec succès.[/bold green]")


def _import_vars(paths: ProjectPaths) -> dict[str, str]:
    return {
        "domain_import": paths.import_path("domain"),
        "application_import": paths.import_path("application"),
        "adapters_import": paths.import_path("adapters"),
        "infrastructure_import": paths.import_path("infrastructure"),
    }


def _file_template_vars(
    project_dir: Path,
    paths: ProjectPaths,
    adapter: AdapterSpec,
    params: dict[str, Any],
) -> dict[str, str]:
    package_path = paths.package_root.relative_to(project_dir).as_posix()
    if package_path == ".":
        langgraph_entrypoint = f"./adapters/inbound/{adapter.name}/agent.py:agent"
    else:
        langgraph_entrypoint = f"./{package_path}/adapters/inbound/{adapter.name}/agent.py:agent"
    graph_name = str(params.get("graph_name") or "agent")
    return {
        "package_path": package_path,
        "langgraph_entrypoint": langgraph_entrypoint,
        "graph_name": graph_name,
    }


def _update_active_capability(project_dir: Path, capability: CapabilitySpec, adapter: AdapterSpec) -> None:
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
            text = re.sub(rf"(?m)^({escaped_key}:\s*).*$", rf"\g<1>{adapter.name}", text)
        else:
            text = text.rstrip("\n") + f"\n{key}: {adapter.name}\n"
        cfg.write_text(text, encoding="utf-8")
    console.print(f"[cyan]↺[/cyan] config/adapters/adapters.yaml → {key}: {adapter.name}")


def _enable_observability_adapter(project_dir: Path, adapter: AdapterSpec) -> None:
    cfg = project_dir / "config" / "adapters" / "adapters.yaml"
    data = _read_yaml_mapping(cfg)
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
    cfg.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(
        f"[cyan]↺[/cyan] config/adapters/adapters.yaml → observability.enabled += {adapter.name}"
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


def _merge_env_file(env_path: Path, updates: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
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
            if not updates[key] and existing_value.strip():
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


def _merge_secrets_file(secrets_path: Path, mappings: tuple[SecretMappingSpec, ...]) -> None:
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_yaml_mapping(secrets_path)
    resolver = data.get("resolver")
    if not isinstance(resolver, str) or not resolver.strip():
        data["resolver"] = "env"

    existing_mappings = data.get("mappings")
    if not isinstance(existing_mappings, dict):
        existing_mappings = {}

    merged_mappings = dict(existing_mappings)
    for mapping in mappings:
        merged_mappings[mapping.field_path] = mapping.secret_key
    data["mappings"] = merged_mappings

    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    secrets_path.write_text(rendered, encoding="utf-8")


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(loaded, dict):
        return dict(loaded)
    return {}


def _ensure_env_is_ignored(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    if ".env" in {line.strip() for line in lines}:
        return
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(".env")
    gitignore.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
