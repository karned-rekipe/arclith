from __future__ import annotations

import shutil
import subprocess
from typing import Annotated

import typer
from rich.console import Console

_INSTALL_URL = "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"

console = Console()


def run_update(ref: str | None = None) -> None:
    uv = shutil.which("uv")
    if not uv:
        console.print(
            "[red]✗[/red] [bold]uv[/bold] introuvable dans le PATH.\n"
            "Installez-le : [link=https://docs.astral.sh/uv/]https://docs.astral.sh/uv/[/link]"
        )
        raise typer.Exit(1)

    url = _INSTALL_URL if not ref else _INSTALL_URL.replace(".git#", f".git@{ref}#")
    console.print(f"[bold]Mise à jour depuis[/bold] [dim]{url}[/dim]")

    result = subprocess.run([uv, "tool", "install", "--force", url])
    if result.returncode == 0:
        console.print("[green]✓[/green] arclith-cli mis à jour")
    else:
        console.print("[red]✗[/red] Échec de la mise à jour")
        raise typer.Exit(result.returncode)
