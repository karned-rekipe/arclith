from pathlib import Path
import subprocess
from typing import Annotated

import typer
from rich.console import Console

from arclith_cli.project_runtime import (
    ProjectRuntimeError,
    RuntimeMode,
    resolve_runtime_command,
    run_foreground,
)

console = Console()


def run_command(
    mode: Annotated[
        RuntimeMode,
        typer.Argument(help="Runtime à lancer : api, mcp_http, mcp_sse, bus ou all."),
    ] = RuntimeMode.API,
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Racine ou sous-répertoire du projet."),
    ] = Path("."),
) -> None:
    """Synchroniser puis lancer un transport du projet en avant-plan."""
    try:
        command = resolve_runtime_command(directory, mode)
        console.print(
            f"[bold cyan]▶ {command.project_name}[/bold cyan] "
            f"[dim]({command.mode.value})[/dim]"
        )
        if command.endpoint is not None:
            console.print(f"[green]↗ {command.endpoint}[/green]")
        console.print(f"[dim]$ {command.display()}[/dim]")
        console.print("[dim]Ctrl+C pour arrêter.[/dim]")
        run_foreground(command)
    except ProjectRuntimeError as exc:
        console.print(f"[bold red]✗ {exc}[/bold red]")
        raise typer.Exit(1) from exc
    except subprocess.CalledProcessError as exc:
        console.print(
            f"[bold red]✗ Le runtime s'est arrêté avec le code {exc.returncode}.[/bold red]"
        )
        raise typer.Exit(exc.returncode) from exc
    except KeyboardInterrupt as exc:
        console.print("\n[yellow]■ Runtime arrêté.[/yellow]")
        raise typer.Exit(130) from exc
