"""CLI for deterministic use case-to-transport bindings."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from arclith_cli.recipe import record_successful_step, snapshot_project_files
from arclith_cli.usecase_binding import apply_binding, plan_binding

console = Console()


def expose_usecase_command(
    usecase: Annotated[
        str, typer.Argument(help="Existing inbound use case port name.")
    ],
    via: Annotated[
        str, typer.Option("--via", help="fastapi, fastmcp, langgraph or rabbitmq")
    ],
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    public_name: Annotated[str | None, typer.Option("--name")] = None,
    http_path: Annotated[str | None, typer.Option("--path")] = None,
    method: Annotated[str | None, typer.Option("--method")] = None,
    status_code: Annotated[int, typer.Option("--status-code")] = 200,
    command_type: Annotated[str | None, typer.Option("--command-type")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    no_record: Annotated[bool, typer.Option("--no-record", hidden=True)] = False,
) -> None:
    """Prepare typed protocol mapping and an explicit registration for one use case."""
    root = Path.cwd()
    args = {
        "usecase": usecase,
        "via": via,
        "feature": feature,
        "public_name": public_name,
        "http_path": http_path,
        "method": method,
        "status_code": status_code,
        "command_type": command_type,
    }
    try:
        plan = plan_binding(root, **args)
        for path in plan.files:
            console.print(
                f"{'update' if path.exists() else 'create'} {path.relative_to(root)}"
            )
        for path in plan.preserved:
            console.print(f"preserve {path.relative_to(root)}")
        if dry_run:
            console.print("Dry-run: no files or recipe changed.")
            return
        before = snapshot_project_files(root) if not no_record else {}
        changed = apply_binding(plan)
        if changed and not no_record:
            record_successful_step(
                root, command="expose-usecase", args=args, before=before
            )
        console.print(
            f"Binding ready ({len(changed)} changed files). "
            "The generated composition root injects this use case into the transport."
        )
    except (ValueError, SyntaxError, OSError) as exc:
        console.print(f"[red]Binding rejected:[/red] {exc}")
        raise typer.Exit(1) from exc
