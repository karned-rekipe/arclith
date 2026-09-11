from pathlib import Path
from typing import Any, Mapping, Never

import typer
from rich.console import Console

from arclith_cli.recipe import RecipeError, record_successful_step
from arclith_cli.recipe_models import RecipeSecretRef

console = Console()


def record_success(
    project_dir: Path,
    *,
    command: str,
    args: Mapping[str, Any],
    before: Mapping[str, str],
    secret_fields: Mapping[str, str] | None = None,
    secret_references: tuple[RecipeSecretRef, ...] = (),
) -> None:
    """Record one completed command and present recipe failures consistently."""
    try:
        record_successful_step(
            project_dir,
            command=command,
            args=args,
            before=before,
            secret_fields=secret_fields,
            secret_references=secret_references,
        )
    except (OSError, RecipeError) as exc:
        _recipe_error(exc)


def _recipe_error(exc: Exception) -> Never:
    console.print(f"[red]✗ Recette CLI invalide :[/red] {exc}")
    raise typer.Exit(1)
