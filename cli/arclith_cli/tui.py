from pathlib import Path

import typer
from rich.markup import escape
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)

from arclith_cli.guide import run_interactive_guide
from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    GuidePlanError,
    GuideStep,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.guide_status import find_project_root
from arclith_cli.tui_dashboard import ProjectDashboardScreen
from arclith_cli.tui_models import ProjectDraft, render_plan
from arclith_cli.tui_project_picker import ProjectPickerScreen
from arclith_cli.tui_wizard_layout import (
    WIZARD_PAGE_IDS,
    WIZARD_STEPS,
    compose_project_wizard,
)


class WelcomeScreen(Screen[None]):
    BINDINGS = [
        ("n", "new_project", "Nouveau projet"),
        ("o", "open_project", "Ouvrir un projet"),
        ("g", "classic_guide", "Guide complet"),
    ]

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start_dir = start_dir

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="welcome-shell"):
            yield Static("◈", id="welcome-mark")
            yield Label("ARCLITH", id="welcome-title")
            yield Static(
                "Construire, inspecter et exécuter un service hexagonal\n"
                "sans quitter le terminal.",
                id="welcome-copy",
            )
            yield Button("Nouveau projet", id="new-project", variant="primary")
            yield Button("Ouvrir un projet", id="open-project")
            yield Button("Guide complet", id="classic-guide")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#new-project", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-project":
            self.action_new_project()
        elif event.button.id == "open-project":
            self.action_open_project()
        elif event.button.id == "classic-guide":
            self.action_classic_guide()

    def action_new_project(self) -> None:
        self.app.push_screen(
            ProjectWizardScreen(self._start_dir),
            self._project_created,
        )

    def action_classic_guide(self) -> None:
        self.app.exit(self._start_dir)

    def action_open_project(self) -> None:
        self.app.push_screen(
            ProjectPickerScreen(self._start_dir),
            self._project_opened,
        )

    def _project_created(self, root: Path | None) -> None:
        if root is not None:
            self.app.switch_screen(ProjectDashboardScreen(root))

    def _project_opened(self, root: Path | None) -> None:
        if root is not None:
            self.app.switch_screen(ProjectDashboardScreen(root))


class ProjectWizardScreen(Screen[Path | None]):
    BINDINGS = [("escape", "cancel", "Retour")]

    def __init__(self, parent_dir: Path) -> None:
        super().__init__()
        self._parent_dir = parent_dir
        self._busy = False
        self._current_step = 0

    def compose(self) -> ComposeResult:
        yield from compose_project_wizard(self._parent_dir)

    def on_mount(self) -> None:
        self.query_one("#creation-progress", ProgressBar).display = False
        self._refresh_intent_fields()
        self._set_step(0)
        self._refresh_plan()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#wizard-sidebar", Vertical).display = event.size.width >= 118
        self.query_one("#plan-panel", VerticalScroll).display = event.size.width >= 90

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_plan()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "intent":
            self._refresh_intent_fields()
        self._refresh_plan()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "previous-step":
            self.action_cancel()
        elif event.button.id == "next-step":
            self._next_step()
        elif event.button.id == "create-project":
            self._request_creation()

    def action_cancel(self) -> None:
        if self._busy:
            self.notify(
                "La génération atomique est en cours.",
                severity="warning",
            )
            return
        if self._current_step > 0:
            self._set_step(self._current_step - 1)
            return
        self.dismiss(None)

    def _next_step(self) -> None:
        if self._current_step == 0:
            self._set_step(1)
            return
        try:
            self._draft().plan()
        except (GuidePlanError, OSError, ValueError) as exc:
            self.query_one("#wizard-error", Static).update(
                f"[red]{escape(str(exc))}[/red]"
            )
            return
        self.query_one("#wizard-error", Static).update("")
        self._set_step(min(self._current_step + 1, len(WIZARD_STEPS) - 1))

    def _refresh_intent_fields(self) -> None:
        intent = self._intent()
        api = intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}
        minimal = intent == ProjectIntent.MINIMAL
        self.query_one("#usecase-field", Vertical).display = intent not in {
            ProjectIntent.MINIMAL,
            ProjectIntent.API_CRUD,
        }
        self.query_one("#repository-field", Vertical).display = not minimal
        self.query_one("#storage-note", Static).display = minimal
        self.query_one("#storage-note", Static).update(
            "Le socle minimal n’installe aucun repository."
        )
        self.query_one("#port-field", Vertical).display = (
            api or intent == ProjectIntent.MCP
        )
        self.query_one("#path-field", Vertical).display = api
        entity_label = "Première entité (facultative)" if minimal else "Première entité"
        self.query_one("#entity-label", Label).update(entity_label)
        self.query_one("#transport-note", Static).update(
            self._transport_description(intent)
        )
        if intent == ProjectIntent.MCP:
            port = self.query_one("#port", Input)
            if port.value == "8000":
                port.value = "8001"
        elif api:
            port = self.query_one("#port", Input)
            if port.value == "8001":
                port.value = "8000"

    def _refresh_plan(self) -> None:
        if not self.is_mounted:
            return
        try:
            preview = render_plan(self._draft().plan())
        except (GuidePlanError, OSError, ValueError) as exc:
            preview = f"[yellow]Plan incomplet[/yellow]\n\n{escape(str(exc))}"
        self.query_one("#plan-preview", Static).update(preview)
        self.query_one("#review-plan", Static).update(preview)

    def _request_creation(self) -> None:
        try:
            plan = self._draft().plan()
        except (GuidePlanError, OSError, ValueError) as exc:
            self.query_one("#wizard-error", Static).update(escape(str(exc)))
            return
        self.query_one("#wizard-error", Static).update("")
        self._set_busy(True)
        self._create_project(plan)

    @work(thread=True, exclusive=True, group="project-creation")
    def _create_project(self, plan: ProjectPlan) -> None:
        try:
            result = execute_project_plan(plan, on_step=self._on_creation_step)
        except (GuidePlanError, OSError, SyntaxError, ValueError, typer.Exit) as exc:
            message = str(exc) or "Une étape Arclith a été refusée."
            self.app.call_from_thread(self._creation_failed, message)
            return
        self.app.call_from_thread(self._creation_succeeded, result.root)

    def _on_creation_step(self, index: int, total: int, step: GuideStep) -> None:
        self.app.call_from_thread(
            self._update_creation_progress, index, total, step.title
        )

    def _update_creation_progress(self, index: int, total: int, title: str) -> None:
        progress = self.query_one("#creation-progress", ProgressBar)
        progress.update(total=total, progress=index - 1)
        self.query_one("#wizard-error", Static).update(
            f"[cyan]{index}/{total}[/cyan] {escape(title)}"
        )

    def _creation_failed(self, message: str) -> None:
        self._set_busy(False)
        self.query_one("#wizard-error", Static).update(f"[red]{escape(message)}[/red]")

    def _creation_succeeded(self, root: Path) -> None:
        progress = self.query_one("#creation-progress", ProgressBar)
        progress.update(progress=progress.total)
        self.notify(f"Projet créé : {root.name}", title="Arclith")
        self.dismiss(root)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.query_one("#create-project", Button).disabled = busy
        self.query_one("#next-step", Button).disabled = busy
        self.query_one("#previous-step", Button).disabled = busy
        self.query_one("#creation-progress", ProgressBar).display = busy

    def _set_step(self, step: int) -> None:
        self._current_step = step
        for index, ((label, _description), page_id) in enumerate(
            zip(WIZARD_STEPS, WIZARD_PAGE_IDS, strict=True)
        ):
            active = index == step
            self.query_one(f"#{page_id}", Vertical).display = active
            indicator = self.query_one(f"#wizard-step-{index}", Static)
            indicator.set_class(active, "is-active")
            indicator.update(f"{'●' if active else '○'}  {label}")
        title, description = WIZARD_STEPS[step]
        self.query_one("#wizard-title", Label).update(title)
        self.query_one("#wizard-description", Static).update(description)
        previous = self.query_one("#previous-step", Button)
        previous.label = "Annuler" if step == 0 else "Précédent"
        self.query_one("#next-step", Button).display = step < len(WIZARD_STEPS) - 1
        self.query_one("#create-project", Button).display = (
            step == len(WIZARD_STEPS) - 1
        )
        self.query_one("#wizard-form", VerticalScroll).scroll_home(animate=False)
        self.call_after_refresh(self._focus_current_step)

    def _focus_current_step(self) -> None:
        focus_targets = (
            "#intent",
            "#parent-dir",
            "#repository" if self._intent() != ProjectIntent.MINIMAL else "#next-step",
            (
                "#port"
                if self._intent()
                in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM, ProjectIntent.MCP}
                else "#next-step"
            ),
            "#create-project",
        )
        self.query_one(focus_targets[self._current_step]).focus()

    @staticmethod
    def _transport_description(intent: ProjectIntent) -> str:
        descriptions = {
            ProjectIntent.API_CRUD: "FastAPI exposera les cinq opérations CRUD.",
            ProjectIntent.API_CUSTOM: "FastAPI exposera le premier cas d’usage.",
            ProjectIntent.MCP: "FastMCP exposera le premier cas d’usage comme outil.",
            ProjectIntent.AGENT: "LangGraph exposera le premier cas d’usage comme nœud.",
            ProjectIntent.WORKER: "RabbitMQ recevra une commande versionnée.",
            ProjectIntent.MINIMAL: "Aucun transport n’est installé pour le socle minimal.",
        }
        return descriptions[intent]

    def _draft(self) -> ProjectDraft:
        return ProjectDraft(
            parent_dir=self.query_one("#parent-dir", Input).value,
            project_name=self.query_one("#project-name", Input).value,
            intent=self._intent(),
            entity=self.query_one("#entity", Input).value,
            usecase=self.query_one("#usecase", Input).value,
            repository=RepositoryChoice(
                str(self.query_one("#repository", Select).value)
            ),
            port=self.query_one("#port", Input).value,
            public_path=self.query_one("#public-path", Input).value,
        )

    def _intent(self) -> ProjectIntent:
        return ProjectIntent(str(self.query_one("#intent", Select).value))


class ArclithTui(App[Path | None]):
    CSS_PATH = "tui.tcss"
    TITLE = "Arclith CLI"
    SUB_TITLE = "Project cockpit"

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start_dir = start_dir

    def on_mount(self) -> None:
        root = find_project_root(self._start_dir)
        if root is None:
            self.push_screen(WelcomeScreen(self._start_dir))
        else:
            self.push_screen(ProjectDashboardScreen(root))


def run_tui(start_dir: Path | None = None) -> None:
    """Run the full-screen project cockpit in the current terminal."""
    selected_dir = ArclithTui((start_dir or Path.cwd()).absolute()).run()
    if selected_dir is not None:
        run_interactive_guide(start_dir=selected_dir)


def tui_command() -> None:
    """Ouvrir le cockpit projet plein écran."""
    run_tui()
