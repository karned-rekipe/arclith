from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def export_config_cmd(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Chemin du fichier YAML généré"),
    ] = Path("config.yaml"),
) -> None:
    """Générer un [bold]config.yaml[/bold] unifié depuis le dossier [bold]config/[/bold].

    Utile pour le déploiement Kubernetes — le fichier généré peut être monté
    directement comme [bold]ConfigMap[/bold]. Arclith l'accepte en lecture via
    [dim]Arclith("config.yaml")[/dim] au même titre que le dossier [dim]config/[/dim].
    """
    project_dir = Path.cwd()
    config_dir = project_dir / "config"

    if not config_dir.is_dir():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]config/[/bold] trouvé.\n"
            "    Exécutez depuis la racine d'un projet arclith."
        )
        raise typer.Exit(1)

    output_path = output if output.is_absolute() else project_dir / output

    if output_path.exists():
        from rich.prompt import Confirm

        if not Confirm.ask(
            f"  [yellow]{output_path.relative_to(project_dir)}[/yellow] existe déjà. Écraser ?",
            default=True,
        ):
            console.print("[yellow]Annulé.[/yellow]")
            raise typer.Exit(0)

    try:
        from arclith.infrastructure.config import export_config_yaml

        export_config_yaml(config_dir, output_path)
    except Exception as exc:
        console.print(f"[red]✗ Erreur :[/red] {exc}")
        raise typer.Exit(1) from exc

    try:
        rel = output_path.relative_to(project_dir)
        display_path = str(rel)
    except ValueError:
        # output_path is outside project_dir (e.g., /tmp/config.yaml)
        display_path = str(output_path)

    console.print(
        Panel.fit(
            f"[green]✓[/green] [bold]{display_path}[/bold] généré depuis [dim]config/[/dim]\n\n"
            f"  [bold cyan]Kubernetes[/bold cyan]  Monter ce fichier comme ConfigMap\n"
            f'  [bold cyan]Arclith[/bold cyan]     [dim]Arclith("{display_path}")[/dim]  ←  identique à  [dim]Arclith("config/")[/dim]\n\n'
            f"  [dim]⚠ Fichier généré — ne pas éditer manuellement.[/dim]\n"
            f"  [dim]  Ajouter [bold]config.yaml[/bold] à .gitignore[/dim]",
            border_style="green",
            title="[bold]export-config[/bold]",
        )
    )
