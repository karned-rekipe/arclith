from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from arclith.infrastructure.project_layout import canonical_project_layout

from .runtime_templates import (
    DOCKERIGNORE_TEMPLATE,
    render_arclith_run,
    render_dockerfile,
)

console = Console()

_PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


def init_project_cmd(
    *,
    project_name: str,
    directory: Path | None = None,
    target_path: Path | None = None,
) -> Path:
    """Create a minimal Arclith project without a starter entity."""
    project_name = project_name.strip()
    _assert_valid_project_name(project_name)

    parent_dir = (directory or Path(".")).resolve()
    target_dir = (
        target_path.resolve() if target_path is not None else parent_dir / project_name
    )
    if target_dir.exists():
        console.print(
            f"[red]✗[/red] Le répertoire existe déjà : [bold]{target_dir}[/bold]"
        )
        raise typer.Exit(1)

    package_name = _to_package(project_name)
    package_root = target_dir / "src" / package_name

    _create_package_layout(package_root)
    _write_project_files(target_dir, project_name, package_name)
    _write_config(target_dir, project_name)
    _write_tests(target_dir, package_name)

    console.print(
        Panel.fit(
            f"[bold blue]arclith-cli[/bold blue]\n\n"
            f"  Projet   [bold]{project_name}[/bold]\n"
            f"  Package  [bold green]{package_name}[/bold green]\n"
            f"  Cible    [dim]{target_dir}[/dim]\n"
            f"  Métier   [dim]vide, à créer avec add-entity et add-usecase[/dim]",
            border_style="blue",
            title="[bold]Projet minimal[/bold]",
        )
    )
    _print_tree(target_dir, project_name)
    return target_dir


def _assert_valid_project_name(project_name: str) -> None:
    if _PROJECT_RE.match(project_name):
        return
    console.print(
        f"[red]✗[/red] Nom de projet invalide : [bold]{project_name}[/bold]. "
        "Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre."
    )
    raise typer.Exit(1)


def _to_package(raw: str) -> str:
    package = raw.replace("-", "_").lower()
    package = re.sub(r"[^a-z0-9_]", "_", package)
    package = re.sub(r"_+", "_", package).strip("_")
    if not package or not package[0].isalpha():
        console.print(
            f"[red]✗[/red] Nom de package Python invalide pour : [bold]{raw}[/bold]."
        )
        raise typer.Exit(1)
    return package


def _framework_version() -> str:
    try:
        return version("arclith")
    except PackageNotFoundError:
        return "0.24.0"


def _create_package_layout(package_root: Path) -> None:
    layout = canonical_project_layout(_to_package(package_root.name))
    for relative in layout.scaffold_directories():
        directory = package_root / relative.relative_to(layout.package_root)
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / "__init__.py").exists():
            (directory / "__init__.py").write_text("", encoding="utf-8")
    if not (package_root / "py.typed").exists():
        (package_root / "py.typed").write_text("", encoding="utf-8")


def _write_project_files(
    target_dir: Path, project_name: str, package_name: str
) -> None:
    framework_version = _framework_version()
    (target_dir / "pyproject.toml").write_text(
        f"""[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{project_name}"
version = "0.1.0"
description = "Arclith service"
requires-python = ">=3.13"
dependencies = [
    "arclith>={framework_version}",
]

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=9.0.0",
    "pytest-asyncio>=1.3.0",
    "httpx>=0.27.0",
]
""",
        encoding="utf-8",
    )
    (target_dir / "README.md").write_text(
        f"""# {project_name}

Projet Arclith minimal.

```bash
uv sync
uv run python -m pytest

# Parcours explicite jusqu'à une API FastAPI
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --entity Todo --yes
arclith-cli add-adapter --capability api --adapter fastapi --yes
arclith-cli expose-usecase create-todo --via fastapi --feature todos \\
  --path /v1/todos --method POST --status-code 201
```

Complétez les champs et l'implémentation du use case, puis composez le binding
généré depuis le point d'entrée. Aucun transport ou adapter métier n'est généré
par `init`.
""",
        encoding="utf-8",
    )
    (target_dir / "AGENTS.md").write_text(
        f"""# {project_name}: architecture contract

Canonical source: `src/{package_name}/{{domain,application,adapters,infrastructure}}`.
Adapter extension points are created only by `arclith-cli add-adapter`.
Keep installed adapter names and locations. Consult their README before adding a component.

- Domain imports no adapter or infrastructure module.
- Application depends on domain models and inbound/outbound ports.
- Inbound adapters map transport DTOs to typed application Command/Query and present Result.
- Use the same application port for FastAPI, MCP, LangGraph and messaging.
- Concrete outbound dependencies are assembled once in infrastructure/containers or bootstrap.
- Keep FastAPI by version/feature, MCP by feature/tools/resources/prompts, LangGraph by capability.
- `__init__.py` has no registration or client side effects.
- Developer-owned files are never overwritten by scaffold replay.
- Only `*_generated.py` files are CLI-owned and may be regenerated.
- Test mapping, application contracts and runtime registration with fake ports before delivery.
- LangGraph state is serializable and versioned; test checkpoint resume when persisted keys change.

Start with `arclith-cli add-entity`, `add-usecase` and `add-adapter`.
Use `uv run python -m pytest` to validate this service.
""",
        encoding="utf-8",
    )
    (target_dir / ".gitignore").write_text(
        """__pycache__/
*.pyc
.venv/
.env
.coverage
htmlcov/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
""",
        encoding="utf-8",
    )
    (target_dir / "main.py").write_text(
        f'''"""Application entrypoint for {project_name}."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from arclith import Arclith
_CONFIG = Path(__file__).parent / "config"
_MODE = os.getenv("MODE", "api")
_VALID_MODES = {{"api", "mcp_http", "mcp_sse", "all", "bus"}}

if _MODE not in _VALID_MODES:
    print(
        f"Unsupported MODE={{_MODE!r}}. Expected one of: {{', '.join(sorted(_VALID_MODES))}}.",
        file=sys.stderr,
    )
    sys.exit(64)

arclith = Arclith(_CONFIG)


def build_api():
    from {package_name}.adapters.inbound.fastapi.register import register_routes

    application = arclith.fastapi()
    register_routes(application)
    return application


def build_mcp():
    from {package_name}.adapters.inbound.fastmcp.register import register_components

    server = arclith.fastmcp("{project_name} MCP")
    register_components(server)
    return server


def _run_bus() -> None:
    # Optional adapter: installed with add-adapter --capability command-bus.
    from arclith.application.command_bus import CommandDispatcher
    from {package_name}.adapters.bidirectional.rabbitmq.register import register_bindings

    dispatcher = CommandDispatcher()
    register_bindings(dispatcher)
    arclith.run_command_bus(dispatcher)


def _run_api() -> None:
    arclith.run_api("main:build_api", factory=True)


def _run_mcp_http() -> None:
    arclith.run_mcp_http(build_mcp())


def _run_mcp_sse() -> None:
    arclith.run_mcp_sse(build_mcp())


if __name__ == "__main__":
    match _MODE:
        case "api":
            arclith.run_with_probes(_run_api, transports=["api"])
        case "mcp_http":
            arclith.run_with_probes(_run_mcp_http, transports=["mcp_http"])
        case "mcp_sse":
            arclith.run_with_probes(_run_mcp_sse, transports=["mcp_sse"])
        case "all":
            arclith.run_with_probes(_run_api, _run_mcp_http, transports=["api", "mcp_http"])
        case "bus":
            arclith.run_with_probes(_run_bus, transports=["bus"])
''',
        encoding="utf-8",
    )
    (target_dir / "Dockerfile").write_text(render_dockerfile(), encoding="utf-8")
    (target_dir / ".dockerignore").write_text(DOCKERIGNORE_TEMPLATE, encoding="utf-8")
    entrypoint = target_dir / "arclith-run"
    entrypoint.write_text(render_arclith_run(), encoding="utf-8")
    entrypoint.chmod(0o755)


def _write_config(target_dir: Path, project_name: str) -> None:
    config_dir = target_dir / "config"
    adapters_dir = config_dir / "adapters"
    inbound_dir = adapters_dir / "inbound"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    (adapters_dir / "outbound").mkdir(parents=True, exist_ok=True)
    (adapters_dir / "bidirectional").mkdir(parents=True, exist_ok=True)

    (config_dir / "app.yaml").write_text(
        f'''name: {project_name}
version: "0.1.0"
description: "{project_name} — built with Arclith"
''',
        encoding="utf-8",
    )
    (adapters_dir / "adapters.yaml").write_text(
        """logger: console
repository: memory
observability:
  enabled: []
""",
        encoding="utf-8",
    )
    (config_dir / "http.yaml").write_text(
        """idempotency:
  enabled: true
  ttl_seconds: 86400
  required: false

etag:
  enabled: true

cache_control:
  get_single_max_age: 300
  get_list_max_age: 60
""",
        encoding="utf-8",
    )
    (config_dir / "soft_delete.yaml").write_text(
        "retention_days: 30\n", encoding="utf-8"
    )
    (inbound_dir / "probe.yaml").write_text(
        """host: 0.0.0.0
port: 9000
enabled: true
""",
        encoding="utf-8",
    )


def _write_tests(target_dir: Path, package_name: str) -> None:
    test_dir = target_dir / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "__init__.py").write_text("", encoding="utf-8")
    (test_dir / "test_project_bootstrap.py").write_text(
        f"""from arclith import Arclith


def test_project_config_loads() -> None:
    app = Arclith("config")

    assert app.config.app.name
    assert app.config.adapters.repository == "memory"


def test_package_imports() -> None:
    import {package_name}

    assert {package_name}.__name__ == "{package_name}"
""",
        encoding="utf-8",
    )


def _print_tree(target_dir: Path, project_name: str) -> None:
    tree = Tree(f"[bold green]{project_name}/[/bold green]")
    _build_tree(tree, target_dir, depth=0, max_depth=3)
    console.print()
    console.print(tree)
    console.print(
        Panel(
            f"[bold cyan]cd[/bold cyan] {target_dir}\n"
            f"[bold cyan]uv sync[/bold cyan]\n"
            f"[bold cyan]arclith-cli add-entity Todo[/bold cyan]\n"
            f"[bold cyan]arclith-cli add-usecase CreateTodo --entity Todo[/bold cyan]\n"
            f"[bold cyan]arclith-cli add-adapter[/bold cyan]  [dim]# toutes les capabilities[/dim]\n"
            f"[bold cyan]arclith-cli expose-usecase create-todo --via fastapi[/bold cyan]",
            title="[bold blue]Next steps[/bold blue]",
            border_style="green",
        )
    )


def _build_tree(node: Tree, path: Path, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return
    children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    for child in children:
        if child.name.startswith("."):
            continue
        label = f"[blue]{child.name}/[/blue]" if child.is_dir() else child.name
        branch = node.add(label)
        if child.is_dir():
            _build_tree(branch, child, depth + 1, max_depth)
