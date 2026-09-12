from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape

from arclith_cli.guide_models import (
    GuidePlanError,
    NewProjectAnswers,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project, shell_command


@dataclass(frozen=True)
class ProjectDraft:
    parent_dir: str
    project_name: str
    intent: ProjectIntent
    entity: str
    usecase: str
    repository: RepositoryChoice
    port: str
    public_path: str

    def plan(self) -> ProjectPlan:
        """Validate the form state through the shared headless planner."""
        minimal = self.intent == ProjectIntent.MINIMAL
        api = self.intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}
        mcp = self.intent == ProjectIntent.MCP
        return plan_new_project(
            NewProjectAnswers(
                parent_dir=Path(self.parent_dir).expanduser(),
                project_name=self.project_name.strip(),
                intent=self.intent,
                entity=self.entity.strip() or None,
                usecase=(
                    self.usecase.strip()
                    if not minimal and self.intent != ProjectIntent.API_CRUD
                    else None
                ),
                repository=None if minimal else self.repository,
                transport_port=self._port() if api or mcp else None,
                public_path=self.public_path.strip() if api else None,
            )
        )

    def _port(self) -> int:
        value = self.port.strip()
        if not value.isdecimal():
            raise GuidePlanError("Le port doit être un entier entre 1 et 65535.")
        return int(value)


def render_plan(plan: ProjectPlan) -> str:
    """Render a compact, auditable plan for the full-screen preview."""
    step_label = "étape" if len(plan.steps) == 1 else "étapes"
    lines = [
        f"[b]{len(plan.steps)} {step_label}[/b] · aucune écriture effectuée",
        "",
    ]
    lines.extend(
        f"[dim]{index:>2}[/dim]  {escape(step.title)}\n"
        f"    [cyan]{escape(shell_command(step))}[/cyan]"
        for index, step in enumerate(plan.steps, start=1)
    )
    return "\n".join(lines)
