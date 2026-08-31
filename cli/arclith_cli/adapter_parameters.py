from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from arclith_cli.capabilities import AdapterSpec, ParameterSpec

console = Console()
_UV_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _resolve_adapter_params(
    adapter: AdapterSpec,
    project_dir: Path,
    *,
    db_name: str | None,
    multitenant: bool | None,
    duckdb_path: str | None,
    extra_params: dict[str, str | bool],
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
    provided_values.update(
        {name: value for name, value in convenience_values.items() if value is not None}
    )

    resolved: dict[str, Any] = {}
    for parameter in adapter.parameters:
        value = _resolve_parameter(
            parameter, provided_values.get(parameter.name), project_dir, prompt_missing
        )
        resolved[parameter.name] = _render_parameter_value(parameter, value)

    return _normalize_adapter_params(adapter, resolved)


def _normalize_adapter_params(
    adapter: AdapterSpec, params: dict[str, Any]
) -> dict[str, Any]:
    normalizers = {
        ("http", "cache-control"): _normalize_cache_control_params,
        ("command-bus", "rabbitmq"): _normalize_rabbitmq_command_bus_params,
        ("runtime", "docker-image"): _normalize_docker_image_params,
        ("agent-persistence", "langgraph"): _normalize_agent_persistence_params,
        ("observability", "langsmith"): _normalize_langsmith_params,
        ("observability", "opentelemetry"): _normalize_opentelemetry_params,
    }
    normalize = normalizers.get((adapter.capability, adapter.name))
    return normalize(params) if normalize is not None else params


def _normalize_langsmith_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    try:
        sampling_rate = float(str(normalized["sampling_rate"]))
    except ValueError:
        console.print(
            "[red]✗[/red] sampling_rate doit être un nombre entre 0.0 et 1.0."
        )
        raise typer.Exit(1) from None
    if not 0.0 <= sampling_rate <= 1.0:
        console.print("[red]✗[/red] sampling_rate doit être compris entre 0.0 et 1.0.")
        raise typer.Exit(1)
    normalized["sampling_rate"] = str(sampling_rate)
    for capture, hide in (
        ("capture_inputs", "hide_inputs"),
        ("capture_outputs", "hide_outputs"),
        ("capture_metadata", "hide_metadata"),
    ):
        enabled = _parse_boolean_param(str(normalized[capture])) is True
        normalized[hide] = _yaml_bool(not enabled)
    return normalized


def _normalize_opentelemetry_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    try:
        sampling_ratio = float(str(normalized["sampling_ratio"]))
    except ValueError:
        console.print(
            "[red]✗[/red] sampling_ratio doit être un nombre entre 0.0 et 1.0."
        )
        raise typer.Exit(1) from None
    if not 0.0 <= sampling_ratio <= 1.0:
        console.print("[red]✗[/red] sampling_ratio doit être compris entre 0.0 et 1.0.")
        raise typer.Exit(1)
    normalized["sampling_ratio"] = str(sampling_ratio)
    try:
        interval = int(str(normalized["metrics_export_interval_millis"]))
    except ValueError:
        console.print(
            "[red]✗[/red] metrics_export_interval_millis doit être un entier positif."
        )
        raise typer.Exit(1) from None
    if interval <= 0:
        console.print("[red]✗[/red] metrics_export_interval_millis doit être > 0.")
        raise typer.Exit(1)
    normalized["metrics_export_interval_millis"] = interval
    return normalized


def _normalize_cache_control_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    for name in ("get_single_max_age", "get_list_max_age"):
        raw_value = str(normalized[name]).strip()
        try:
            value = int(raw_value)
        except ValueError:
            console.print(
                f"[red]✗[/red] Valeur entière invalide pour [bold]{name}[/bold]: {raw_value}."
            )
            raise typer.Exit(1) from None
        if value < 0:
            console.print(
                f"[red]✗[/red] Valeur invalide pour [bold]{name}[/bold]: {value}. "
                "Utilisez une valeur >= 0."
            )
            raise typer.Exit(1)
        normalized[name] = value
    return normalized


def _normalize_rabbitmq_command_bus_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    for name in ("prefetch", "concurrency"):
        raw_value = str(normalized[name]).strip()
        try:
            value = int(raw_value)
        except ValueError:
            console.print(
                f"[red]✗[/red] Valeur entière invalide pour [bold]{name}[/bold]: {raw_value}."
            )
            raise typer.Exit(1) from None
        if value <= 0:
            console.print(
                f"[red]✗[/red] Valeur invalide pour [bold]{name}[/bold]: {value}. "
                "Utilisez une valeur > 0."
            )
            raise typer.Exit(1)
        normalized[name] = value
    return normalized


def _normalize_docker_image_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    uv_version = str(normalized["uv_version"]).strip()
    if not _UV_VERSION_RE.fullmatch(uv_version):
        console.print(
            "[red]✗[/red] Version uv invalide: utilisez un token sans espace, accolade ou saut de ligne."
        )
        raise typer.Exit(1)
    normalized["uv_version"] = uv_version

    for name in ("api_port", "mcp_port", "probe_port", "agent_port"):
        raw_value = str(normalized[name]).strip()
        try:
            value = int(raw_value)
        except ValueError:
            console.print(
                f"[red]✗[/red] Port entier invalide pour [bold]{name}[/bold]: {raw_value}."
            )
            raise typer.Exit(1) from None
        if value <= 0 or value > 65535:
            console.print(
                f"[red]✗[/red] Port invalide pour [bold]{name}[/bold]: {value}. "
                "Utilisez une valeur entre 1 et 65535."
            )
            raise typer.Exit(1)
        normalized[name] = value
    return normalized


def _normalize_agent_persistence_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    raw_ttl = str(normalized["ttl_seconds"]).strip()
    if not raw_ttl:
        normalized["ttl_seconds"] = None
        return normalized
    try:
        ttl_seconds = int(raw_ttl)
    except ValueError:
        console.print(
            f"[red]✗[/red] TTL entier invalide pour [bold]ttl_seconds[/bold]: {raw_ttl}."
        )
        raise typer.Exit(1) from None
    if ttl_seconds <= 0:
        console.print("[red]✗[/red] ttl_seconds doit etre strictement positif ou vide.")
        raise typer.Exit(1)
    normalized["ttl_seconds"] = ttl_seconds
    return normalized


def _assert_supported_params(
    adapter: AdapterSpec,
    extra_params: dict[str, str | bool],
) -> None:
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
        prompt_kwargs: dict[str, Any] = {"password": parameter.secret}
        if string_default:
            prompt_kwargs["default"] = string_default
        resolved = Prompt.ask(f"  {parameter.prompt}", **prompt_kwargs).strip()
    resolved = resolved or string_default
    if parameter.required and not resolved:
        console.print(
            f"[red]✗[/red] Paramètre requis manquant: [bold]{parameter.name}[/bold]."
        )
        raise typer.Exit(1)
    _assert_allowed_parameter_value(parameter, resolved)
    return resolved


def _assert_allowed_parameter_value(parameter: ParameterSpec, value: str) -> None:
    if not parameter.choices:
        return

    values = _split_csv_values(value) if parameter.csv_choices else [value.strip()]
    unknown = [item for item in values if item not in parameter.choices]
    if not unknown:
        return

    allowed = ", ".join(parameter.choices)
    received = ", ".join(unknown)
    console.print(
        f"[red]✗[/red] Valeur invalide pour [bold]{parameter.name}[/bold]: {received}. "
        f"Valeurs: {allowed}."
    )
    raise typer.Exit(1)


def _split_csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


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
