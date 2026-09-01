from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from arclith_cli import __version__
from arclith_cli.rename import EntityNames, apply_rename
from arclith_cli.runtime_templates import (
    DOCKERIGNORE_TEMPLATE,
    render_arclith_run,
    render_dockerfile,
)
from arclith_cli.scaffold import download_and_extract

console = Console()


def new_project_cmd(
    *,
    entity: str,
    project_name: str,
    directory: Path,
    port: int,
    repo_ref: str,
    template_dir: Path | None,
    target_path: Path | None = None,
) -> Path:
    """Create a template-based project and return its root for recipe recording."""
    _validate_runtime_ports(api_port=port, mcp_port=port + 1)

    names = EntityNames.from_input(entity)
    target_dir = (
        target_path.resolve()
        if target_path is not None
        else directory.resolve() / project_name
    )

    if target_dir.exists():
        console.print(
            f"[red]✗[/red] Le répertoire existe déjà : [bold]{target_dir}[/bold]"
        )
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            f"[bold blue]arclith-cli[/bold blue] [dim]v{__version__}[/dim]\n\n"
            f"  Entité   [bold green]{names.pascal}[/bold green]  "
            f"[dim]({names.snake} / {names.upper})[/dim]\n"
            f"  Projet   [bold]{project_name}[/bold]\n"
            f"  Cible    [dim]{target_dir}[/dim]\n"
            f"  Ports    REST [bold]{port}[/bold]  ·  MCP [bold]{port + 1}[/bold]",
            border_style="blue",
            title="[bold]Nouveau projet[/bold]",
        )
    )

    with console.status("[bold]Préparation du template…[/bold]"):
        try:
            download_and_extract(target_dir, ref=repo_ref, template_dir=template_dir)
        except Exception as exc:
            console.print(f"[red]✗ Téléchargement échoué :[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print("[green]✓[/green] Template extrait")

    with console.status("[bold]Renommage de l'entité…[/bold]"):
        apply_rename(target_dir, names, project_name=project_name, port=port)
        _write_runtime_files(target_dir, api_port=port, mcp_port=port + 1)

    console.print("[green]✓[/green] Renommage terminé")
    _print_summary(target_dir, project_name, port)
    return target_dir


def _write_runtime_files(target_dir: Path, *, api_port: int, mcp_port: int) -> None:
    _validate_runtime_ports(api_port=api_port, mcp_port=mcp_port)
    (target_dir / "Dockerfile").write_text(
        render_dockerfile(api_port=str(api_port), mcp_port=str(mcp_port)),
        encoding="utf-8",
    )
    (target_dir / ".dockerignore").write_text(DOCKERIGNORE_TEMPLATE, encoding="utf-8")
    entrypoint = target_dir / "arclith-run"
    entrypoint.write_text(render_arclith_run(), encoding="utf-8")
    entrypoint.chmod(0o755)


def _validate_runtime_ports(*, api_port: int, mcp_port: int) -> None:
    for label, value in (("REST", api_port), ("MCP", mcp_port)):
        if value <= 0 or value > 65535:
            console.print(
                f"[red]✗[/red] Port {label} invalide: [bold]{value}[/bold]. "
                "Utilisez une valeur entre 1 et 65535."
            )
            raise typer.Exit(1)


def _print_summary(target_dir: Path, project_name: str, port: int) -> None:
    tree = Tree(f"[bold green]{project_name}/[/bold green]")
    _build_tree(tree, target_dir, depth=0, max_depth=3)
    console.print()
    console.print(tree)
    console.print(
        Panel(
            f"[bold cyan]cd[/bold cyan] {target_dir}\n"
            f"[bold cyan]uv sync[/bold cyan]\n\n"
            f"[bold cyan]uv run python main.py[/bold cyan]"
            f"  [dim]# MODE=api → REST :{port}[/dim]\n"
            f"[bold cyan]MODE=mcp_http uv run python main.py[/bold cyan]"
            f"  [dim]# MCP :{port + 1}[/dim]",
            title="[bold blue]Next steps[/bold blue]",
            border_style="green",
        )
    )


def _build_tree(node: Tree, path: Path, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return
    try:
        children = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name))
    except PermissionError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        label = f"[blue]{child.name}/[/blue]" if child.is_dir() else child.name
        branch = node.add(label)
        if child.is_dir():
            _build_tree(branch, child, depth + 1, max_depth)
