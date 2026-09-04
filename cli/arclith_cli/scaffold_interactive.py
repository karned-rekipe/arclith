from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from .entity_scanner import scan_entities

console = Console()

_ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class UseCaseEntityChoice:
    entity_name: str | None = None
    new_entity_name: str | None = None
    no_entity: bool = False


def resolve_usecase_entity_choice(
    *,
    project_dir: Path,
    entity_name: str | None,
    new_entity_name: str | None,
    no_entity: bool,
) -> UseCaseEntityChoice:
    provided_modes = sum(
        value is not None and value is not False
        for value in (entity_name, new_entity_name, no_entity)
    )
    if provided_modes > 1:
        console.print(
            "[red]✗[/red] Les options [bold]--entity[/bold], "
            "[bold]--new-entity[/bold] et [bold]--no-entity[/bold] "
            "sont mutuellement exclusives."
        )
        raise typer.Exit(1)
    if entity_name is not None:
        return UseCaseEntityChoice(entity_name=entity_name)
    if new_entity_name is not None:
        return UseCaseEntityChoice(new_entity_name=new_entity_name)
    if no_entity:
        return UseCaseEntityChoice(no_entity=True)

    entities = scan_entities(project_dir)
    if entities:
        console.print("\n[bold]Entité principale du cas d'usage[/bold]")
        labels = [entity.pascal for entity in entities]
        labels.extend(
            ("Créer une nouvelle entité", "Aucune entité / cas d'usage transverse")
        )
        selected = _prompt_numbered_choice(labels)
        if selected <= len(entities):
            return UseCaseEntityChoice(entity_name=entities[selected - 1].pascal)
        if selected == len(entities) + 1:
            return UseCaseEntityChoice(new_entity_name=_prompt_entity_name())
        return UseCaseEntityChoice(no_entity=True)

    console.print("\n[yellow]Aucune entité détectée.[/yellow]")
    selected = _prompt_numbered_choice(
        [
            "Créer une nouvelle entité maintenant",
            "Continuer avec un cas d'usage transverse",
            "Annuler",
        ]
    )
    if selected == 1:
        return UseCaseEntityChoice(new_entity_name=_prompt_entity_name())
    if selected == 2:
        return UseCaseEntityChoice(no_entity=True)
    console.print("[yellow]Création annulée.[/yellow]")
    raise typer.Exit(0)


def _prompt_numbered_choice(labels: list[str]) -> int:
    for index, label in enumerate(labels, start=1):
        console.print(f"  [cyan]{index}[/cyan]. {label}")
    choice = Prompt.ask(
        "  [bold green]Choix[/bold green]",
        choices=[str(index) for index in range(1, len(labels) + 1)],
        default="1",
    )
    return int(choice)


def _prompt_entity_name() -> str:
    while True:
        value = Prompt.ask(
            "  [bold green]Nom de la nouvelle entité[/bold green]"
        ).strip()
        if not value:
            console.print("  [red]Le nom ne peut pas être vide.[/red]")
        elif not _ENTITY_RE.match(value):
            console.print(
                "  [red]Caractères invalides.[/red] "
                "[dim]Lettres, chiffres, _ et - uniquement. "
                "Doit commencer par une lettre.[/dim]"
            )
        else:
            return value
