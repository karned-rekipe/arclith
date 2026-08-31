from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from arclith_cli.adapter_config import ARCLITH_DEPENDENCY_RE, read_yaml_mapping
from arclith_cli.adapter_parameters import _parse_boolean_param, _split_csv_values
from arclith_cli.capabilities import AdapterSpec
from arclith_cli.project_paths import ProjectPaths

console = Console()


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
        langgraph_entrypoint = (
            f"./{package_path}/adapters/inbound/{adapter.name}/agent.py:agent"
        )
    graph_name = str(params.get("graph_name") or "agent")
    return {
        "package_path": package_path,
        "langgraph_entrypoint": langgraph_entrypoint,
        "graph_name": graph_name,
        "stream_mode_yaml": _langgraph_stream_mode_yaml(
            str(params.get("stream_mode") or "updates")
        ),
        "persistence_config_yaml": _langgraph_persistence_yaml(params),
        "secret_template_yaml": _secret_template_yaml(
            str(params.get("field_path") or "")
        ),
        "secret_chain_yaml": _secret_chain_yaml(str(params.get("resolvers") or "")),
    }


def _langgraph_stream_mode_yaml(stream_mode: str) -> str:
    values = _split_csv_values(stream_mode)
    if len(values) == 1:
        return f'"{values[0]}"'
    return yaml.safe_dump(values, default_flow_style=True, sort_keys=False).strip()


def _langgraph_persistence_yaml(params: dict[str, Any]) -> str:
    checkpointer_adapter = str(params.get("checkpointer") or "memory")
    store_adapter = str(params.get("store") or "memory")
    database = str(params.get("database") or "langgraph")
    checkpointer: dict[str, Any] = {
        "adapter": checkpointer_adapter,
        "setup": _parse_boolean_param(str(params.get("checkpointer_setup", "false")))
        is True,
        "ttl_seconds": params.get("ttl_seconds"),
    }
    if checkpointer_adapter == "sqlite":
        checkpointer["path"] = str(
            params.get("sqlite_path") or ".arclith/langgraph-checkpoints.sqlite"
        )
    elif checkpointer_adapter == "postgresql":
        checkpointer.update(
            connection_uri_env="POSTGRESQL_URL",
            database=database,
        )
    elif checkpointer_adapter == "mongodb":
        checkpointer.update(connection_uri_env="MONGODB_URI", database=database)
    elif checkpointer_adapter == "custom" and params.get("checkpointer_factory"):
        checkpointer["factory"] = str(params["checkpointer_factory"])

    store: dict[str, Any] = {
        "adapter": store_adapter,
        "setup": _parse_boolean_param(str(params.get("store_setup", "false"))) is True,
        "namespace_template": str(
            params.get("namespace_template") or "{tenant_id}:{user_id}:memories"
        ),
        "semantic_search": {
            "enabled": False,
            "embed": None,
            "dims": None,
            "fields": ["$"],
        },
    }
    if store_adapter == "postgresql":
        store.update(connection_uri_env="POSTGRESQL_URL", database=database)
    elif store_adapter == "mongodb":
        store.update(
            connection_uri_env="MONGODB_URI",
            database=database,
            collection="memories",
        )
    elif store_adapter == "redis":
        store["connection_uri_env"] = "REDIS_URL"
    elif store_adapter == "custom" and params.get("store_factory"):
        store["factory"] = str(params["store_factory"])

    return yaml.safe_dump(
        {
            "persistence": {
                "enabled": True,
                "mode": str(params.get("mode") or "auto"),
                "checkpointer": checkpointer,
                "store": store,
            }
        },
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")


def _agent_persistence_extras(params: dict[str, Any]) -> tuple[str, ...]:
    extras = ["langgraph"]
    by_backend = {
        "sqlite": "langgraph-persistence-sqlite",
        "postgresql": "langgraph-persistence-postgresql",
        "mongodb": "langgraph-persistence-mongodb",
        "redis": "langgraph-persistence-redis",
    }
    for backend in (str(params.get("checkpointer")), str(params.get("store"))):
        extra = by_backend.get(backend)
        if extra is not None and extra not in extras:
            extras.append(extra)
    return tuple(extras)


def _configured_agent_persistence_extras(
    project_dir: Path,
    fallback: dict[str, Any],
) -> tuple[str, ...]:
    langgraph_config = read_yaml_mapping(
        project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml"
    )
    persistence = langgraph_config.get("persistence")
    if not isinstance(persistence, dict):
        return _agent_persistence_extras(fallback)
    checkpointer = persistence.get("checkpointer")
    store = persistence.get("store")
    configured = {
        "checkpointer": (
            checkpointer.get("adapter") if isinstance(checkpointer, dict) else None
        ),
        "store": store.get("adapter") if isinstance(store, dict) else None,
    }
    return _agent_persistence_extras(configured)


def _ensure_arclith_extras(project_dir: Path, required: tuple[str, ...]) -> None:
    pyproject = project_dir / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = ARCLITH_DEPENDENCY_RE.search(text)
    if match is None:
        raise typer.Exit(1)
    current = [
        extra.strip()
        for extra in (match.group("extras") or "").split(",")
        if extra.strip()
    ]
    if "all" in current:
        return
    merged = current + [extra for extra in required if extra not in current]
    if merged == current:
        return
    quote = match.group("quote")
    constraint = match.group("constraint")
    replacement = f"{quote}arclith[{','.join(merged)}]{constraint}{quote}"
    updated = text[: match.start()] + replacement + text[match.end() :]
    pyproject.write_text(updated, encoding="utf-8")
    console.print(
        "[cyan]↺[/cyan] pyproject.toml → extras arclith: " + ", ".join(merged)
    )


def _secret_template_yaml(field_path: str) -> str:
    keys = [key for key in field_path.split(".") if key]
    if not keys:
        return "# Ajouter les secrets locaux ici."

    data: dict[str, Any] = {}
    current = data
    for key in keys[:-1]:
        current[key] = {}
        current = current[key]
    current[keys[-1]] = "replace-me"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip("\n")


def _secret_chain_yaml(resolvers: str) -> str:
    values = _split_csv_values(resolvers or "env,vault,yaml")
    return "".join(f"  - {value}\n" for value in values).rstrip("\n")
