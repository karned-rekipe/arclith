from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import shutil
import subprocess

import yaml

from arclith_cli.guide_models import ProjectOverview
from arclith_cli.guide_status import find_project_root, inspect_project


class ProjectRuntimeError(ValueError):
    """Raised when a generated project cannot run the requested transport."""


class RuntimeMode(StrEnum):
    API = "api"
    MCP_HTTP = "mcp_http"
    MCP_SSE = "mcp_sse"
    BUS = "bus"
    ALL = "all"


@dataclass(frozen=True)
class RuntimeCommand:
    root: Path
    project_name: str
    mode: RuntimeMode
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    endpoint: str | None

    def display(self) -> str:
        assignments = " ".join(f"{key}={value}" for key, value in self.environment)
        command = " ".join(self.argv)
        return f"{assignments} {command}".strip()

    def process_environment(
        self,
        base: Mapping[str, str] = os.environ,
    ) -> dict[str, str]:
        environment = dict(base)
        environment.update(self.environment)
        return environment


def available_runtime_modes(overview: ProjectOverview) -> tuple[RuntimeMode, ...]:
    """Return runnable modes inferred from installed transport manifests."""
    adapters = set(overview.adapters)
    modes: list[RuntimeMode] = []
    if "api/fastapi" in adapters:
        modes.append(RuntimeMode.API)
    if "mcp/fastmcp" in adapters:
        modes.extend((RuntimeMode.MCP_HTTP, RuntimeMode.MCP_SSE))
    if "command-bus/rabbitmq" in adapters:
        modes.append(RuntimeMode.BUS)
    if {"api/fastapi", "mcp/fastmcp"}.issubset(adapters):
        modes.append(RuntimeMode.ALL)
    return tuple(modes)


def resolve_runtime_command(
    directory: Path,
    mode: RuntimeMode,
) -> RuntimeCommand:
    """Build the foreground command for one generated-project runtime."""
    root = find_project_root(directory)
    if root is None:
        raise ProjectRuntimeError(
            f"Projet Arclith introuvable depuis : {directory.absolute()}"
        )
    overview = inspect_project(root)
    if mode not in available_runtime_modes(overview):
        available = ", ".join(item.value for item in available_runtime_modes(overview))
        suffix = available or "aucun transport exécutable"
        raise ProjectRuntimeError(
            f"Mode {mode.value!r} indisponible pour {overview.name}. "
            f"Modes détectés : {suffix}."
        )
    if not (root / "main.py").is_file():
        raise ProjectRuntimeError(f"Point d'entrée absent : {root / 'main.py'}")
    if shutil.which("uv") is None:
        raise ProjectRuntimeError(
            "La commande 'uv' est requise pour synchroniser et lancer le projet."
        )
    return RuntimeCommand(
        root=root,
        project_name=overview.name,
        mode=mode,
        argv=("uv", "run", "python", "main.py"),
        environment=(("MODE", mode.value),),
        endpoint=_runtime_endpoint(root, mode),
    )


def run_foreground(command: RuntimeCommand) -> None:
    """Run a project in the foreground and preserve its native terminal output."""
    subprocess.run(
        command.argv,
        check=True,
        cwd=command.root,
        env=command.process_environment(),
    )


def _runtime_endpoint(root: Path, mode: RuntimeMode) -> str | None:
    if mode in {RuntimeMode.API, RuntimeMode.ALL}:
        return _http_endpoint(root / "config/adapters/inbound/fastapi.yaml")
    if mode in {RuntimeMode.MCP_HTTP, RuntimeMode.MCP_SSE}:
        return _http_endpoint(root / "config/adapters/inbound/fastmcp.yaml")
    return None


def _http_endpoint(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectRuntimeError(
            f"Configuration runtime invalide ({path}) : {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ProjectRuntimeError(f"Configuration runtime invalide : {path}")
    host = raw.get("host")
    port = raw.get("port")
    if not isinstance(host, str) or not isinstance(port, int | str):
        raise ProjectRuntimeError(f"Host ou port runtime invalide : {path}")
    unspecified_hosts = {".".join(("0", "0", "0", "0")), "::"}
    display_host = "127.0.0.1" if host in unspecified_hosts else host
    return f"http://{display_host}:{port}"
