from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arclith_cli.capabilities import CAPABILITY_CATALOG
from arclith_cli.guide_models import GuideStep, ProjectOverview, ProjectPlan
from arclith_cli.guide_planner import shell_command


class GuideRenderer:
    def __init__(self, console: Console) -> None:
        self._console = console

    def welcome(self) -> None:
        self._console.print(
            Panel.fit(
                "Créez et faites évoluer un projet hexagonal, étape par étape.\n"
                "[dim]Chaque écriture est précédée d'un plan explicite.[/dim]",
                title="[bold blue]Arclith — guide projet[/bold blue]",
                border_style="blue",
            )
        )

    def plan(self, plan: ProjectPlan) -> None:
        table = Table(show_header=True, header_style="bold blue", box=None)
        table.add_column("#", justify="right")
        table.add_column("Décision")
        table.add_column("Commande équivalente", style="dim")
        for index, step in enumerate(plan.steps, start=1):
            table.add_row(str(index), step.title, shell_command(step))
        self._console.print(
            Panel(
                table,
                title=f"Plan — {plan.target_dir}",
                border_style="cyan",
            )
        )

    def overview(self, overview: ProjectOverview) -> None:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Élément", style="bold")
        table.add_column("État")
        table.add_row("Projet", overview.name)
        table.add_row("Package", overview.package)
        table.add_row("Entités", _list_or_empty(overview.entities))
        table.add_row("Cas d'usage", _list_or_empty(overview.usecases))
        table.add_row(
            "Features",
            _list_or_empty(tuple(feature.name for feature in overview.features)),
        )
        table.add_row("Adapters", _list_or_empty(overview.adapters))
        health = (
            "[green]sain[/green]"
            if not overview.issues
            else f"[yellow]{len(overview.issues)} point(s) à vérifier[/yellow]"
        )
        table.add_row("Diagnostic", health)
        self._console.print(
            Panel(table, title=f"[bold]{overview.name}[/bold]", border_style="blue")
        )
        for issue in overview.issues:
            self._console.print(f"  [yellow]•[/yellow] {issue}")

    def capabilities(self) -> None:
        table = Table(show_header=True, header_style="bold blue", box=None)
        table.add_column("Capacité")
        table.add_column("Couche")
        table.add_column("Adapters")
        table.add_column("Rôle")
        for capability in CAPABILITY_CATALOG:
            table.add_row(
                capability.name,
                capability.layer,
                ", ".join(capability.adapter_names()),
                capability.description,
            )
        self._console.print(Panel(table, title="Catalogue des capacités"))

    def advanced_commands(self) -> None:
        self._console.print(
            Panel(
                "[bold]Inspection[/bold]  capabilities, blueprints, history\n"
                "[bold]Scaffold[/bold]    init, new, add-entity, add-usecase, "
                "add-blueprint, add-adapter, add-intent-interpreter\n"
                "[bold]Exposition[/bold]  expose-usecase, expose-feature\n"
                "[bold]Configuration[/bold] export-config\n"
                "[bold]Rejeu[/bold]       replay\n\n"
                "[bold]Maintenance[/bold] version, update\n\n"
                "Utilisez [cyan]arclith-cli <commande> --help[/cyan] pour les "
                "options avancées.",
                title="Commandes directes",
            )
        )

    def success(self, message: str) -> None:
        self._console.print(f"[bold green]✓ {message}[/bold green]")

    def progress(self, index: int, total: int, step: GuideStep) -> None:
        self._console.print(f"[cyan]{index}/{total}[/cyan] {step.title}…")

    def warning(self, message: str) -> None:
        self._console.print(f"[yellow]{message}[/yellow]")

    def error(self, message: str) -> None:
        self._console.print(f"[bold red]✗ {message}[/bold red]")


def _list_or_empty(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "[dim]aucun[/dim]"
