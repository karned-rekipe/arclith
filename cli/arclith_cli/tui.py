from pathlib import Path

import typer
from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Select,
    Static,
)

from arclith_cli.guide import run_interactive_guide
from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    GuidePlanError,
    GuideStep,
    ProjectIntent,
    ProjectOverview,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.guide_status import find_project_root, inspect_project
from arclith_cli.project_runtime import (
    ProjectRuntimeError,
    RuntimeCommand,
    RuntimeMode,
    available_runtime_modes,
    resolve_runtime_command,
)
from arclith_cli.tui_models import ProjectDraft, render_plan
from arclith_cli.tui_runtime import ManagedRuntime


_INTENT_OPTIONS = (
    ("API REST CRUD", ProjectIntent.API_CRUD.value),
    ("API REST sur mesure", ProjectIntent.API_CUSTOM.value),
    ("Serveur MCP", ProjectIntent.MCP.value),
    ("Agent LangGraph", ProjectIntent.AGENT.value),
    ("Worker RabbitMQ", ProjectIntent.WORKER.value),
    ("Socle minimal", ProjectIntent.MINIMAL.value),
)
_REPOSITORY_OPTIONS = (
    ("Mémoire — rapide et non persistant", RepositoryChoice.MEMORY.value),
    ("MongoDB — documentaire asynchrone", RepositoryChoice.MONGODB.value),
    ("PostgreSQL — JSONB et transactions", RepositoryChoice.POSTGRESQL.value),
)
_RUNTIME_LABELS = {
    RuntimeMode.API: "API FastAPI",
    RuntimeMode.MCP_HTTP: "MCP HTTP",
    RuntimeMode.MCP_SSE: "MCP SSE",
    RuntimeMode.BUS: "Worker RabbitMQ",
    RuntimeMode.ALL: "API + MCP",
}


class WelcomeScreen(Screen[None]):
    BINDINGS = [
        ("n", "new_project", "Nouveau projet"),
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
            yield Button("Guide complet", id="classic-guide")
            yield Label("Ouvrir un projet existant", classes="field-label")
            yield Input(value=str(self._start_dir), id="open-project-path")
            yield Button("Ouvrir", id="open-project")
            yield Static("", id="welcome-error", classes="error-message")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#new-project", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-project":
            self.action_new_project()
        elif event.button.id == "open-project":
            self._open_project()
        elif event.button.id == "classic-guide":
            self.action_classic_guide()

    def action_new_project(self) -> None:
        self.app.push_screen(
            ProjectWizardScreen(self._start_dir),
            self._project_created,
        )

    def action_classic_guide(self) -> None:
        self.app.exit(self._start_dir)

    def _open_project(self) -> None:
        raw_path = self.query_one("#open-project-path", Input).value.strip()
        path = Path(raw_path).expanduser()
        root = find_project_root(path)
        if root is None:
            self.query_one("#welcome-error", Static).update(
                f"Projet Arclith introuvable depuis {escape(str(path.absolute()))}."
            )
            return
        self.app.switch_screen(ProjectDashboardScreen(root))

    def _project_created(self, root: Path | None) -> None:
        if root is not None:
            self.app.switch_screen(ProjectDashboardScreen(root))


class ProjectWizardScreen(Screen[Path | None]):
    BINDINGS = [("escape", "cancel", "Retour")]

    def __init__(self, parent_dir: Path) -> None:
        super().__init__()
        self._parent_dir = parent_dir
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="wizard-shell"):
            with Vertical(id="wizard-sidebar"):
                yield Label("NOUVEAU PROJET", classes="section-title")
                yield Static("●  Intention", classes="wizard-step is-active")
                yield Static("○  Domaine", classes="wizard-step")
                yield Static("○  Stockage", classes="wizard-step")
                yield Static("○  Transport", classes="wizard-step")
                yield Static("○  Vérification", classes="wizard-step")
                yield Static(
                    "Le plan est calculé par le même moteur que les commandes directes.",
                    id="wizard-note",
                )
            with VerticalScroll(id="wizard-form"):
                yield Static("CRÉATION GUIDÉE", classes="eyebrow")
                yield Label("Configurer le service", id="wizard-title")
                yield Static(
                    "Toutes les décisions restent modifiables avant l’écriture atomique.",
                    classes="lead",
                )
                yield Label("Résultat attendu", classes="field-label")
                yield Select(
                    _INTENT_OPTIONS,
                    value=ProjectIntent.API_CRUD.value,
                    allow_blank=False,
                    id="intent",
                )
                yield Label("Répertoire parent", classes="field-label")
                yield Input(value=str(self._parent_dir), id="parent-dir")
                yield Label("Nom du projet", classes="field-label")
                yield Input(value="catalog-service", id="project-name")
                with Vertical(id="entity-field", classes="form-field"):
                    yield Label("Première entité", classes="field-label")
                    yield Input(value="Product", id="entity")
                with Vertical(id="usecase-field", classes="form-field"):
                    yield Label("Premier cas d’usage", classes="field-label")
                    yield Input(value="CreateProduct", id="usecase")
                with Vertical(id="repository-field", classes="form-field"):
                    yield Label("Repository explicite", classes="field-label")
                    yield Select(
                        _REPOSITORY_OPTIONS,
                        value=RepositoryChoice.MEMORY.value,
                        allow_blank=False,
                        id="repository",
                    )
                with Vertical(id="port-field", classes="form-field"):
                    yield Label("Port", classes="field-label")
                    yield Input(value="8000", id="port", type="integer")
                with Vertical(id="path-field", classes="form-field"):
                    yield Label("Chemin HTTP", classes="field-label")
                    yield Input(value="/v1/products", id="public-path")
                yield Static("", id="wizard-error", classes="error-message")
                with Horizontal(classes="action-row"):
                    yield Button("Retour", id="cancel-project")
                    yield Button(
                        "Créer le projet", id="create-project", variant="primary"
                    )
                yield ProgressBar(total=1, show_eta=False, id="creation-progress")
            with VerticalScroll(id="plan-panel"):
                yield Label("PLAN DE GÉNÉRATION", classes="section-title")
                yield Static("", id="plan-preview")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#creation-progress", ProgressBar).display = False
        self._refresh_intent_fields()
        self._refresh_plan()
        self.query_one("#project-name", Input).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#wizard-sidebar", Vertical).display = event.size.width >= 100
        self.query_one("#plan-panel", VerticalScroll).display = event.size.width >= 72

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_plan()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "intent":
            self._refresh_intent_fields()
        self._refresh_plan()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-project":
            self.action_cancel()
        elif event.button.id == "create-project":
            self._request_creation()

    def action_cancel(self) -> None:
        if self._busy:
            self.notify(
                "La génération atomique est en cours.",
                severity="warning",
            )
            return
        self.dismiss(None)

    def _refresh_intent_fields(self) -> None:
        intent = self._intent()
        api = intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}
        self.query_one("#usecase-field", Vertical).display = intent not in {
            ProjectIntent.MINIMAL,
            ProjectIntent.API_CRUD,
        }
        self.query_one("#repository-field", Vertical).display = (
            intent != ProjectIntent.MINIMAL
        )
        self.query_one("#port-field", Vertical).display = (
            api or intent == ProjectIntent.MCP
        )
        self.query_one("#path-field", Vertical).display = api
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
        self.query_one("#cancel-project", Button).disabled = busy
        self.query_one("#creation-progress", ProgressBar).display = busy

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


class ProjectDashboardScreen(Screen[None]):
    BINDINGS = [
        ("r", "refresh_project", "Actualiser"),
        ("s", "start_runtime", "Démarrer"),
        ("x", "stop_runtime", "Arrêter"),
        ("n", "new_project", "Nouveau"),
        ("g", "classic_guide", "Guide complet"),
        ("q", "request_quit", "Quitter"),
    ]

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._project_root = project_root
        self._overview: ProjectOverview | None = None
        self._runtime = ManagedRuntime()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="dashboard-shell"):
            with Vertical(id="project-sidebar"):
                yield Static("◈  ARCLITH", id="project-brand")
                yield Button("Vue projet", id="nav-project", variant="primary")
                yield Button("Nouveau projet", id="nav-new")
                yield Button("Guide complet", id="nav-guide")
                yield Button("Actualiser", id="nav-refresh")
                yield Static("", id="project-location")
            with VerticalScroll(id="project-content"):
                yield Static("PROJET COURANT", classes="eyebrow")
                yield Label("", id="project-title")
                yield Static("", id="project-summary", classes="lead")
                with Horizontal(id="project-metrics"):
                    yield Static("", id="metric-entities", classes="metric")
                    yield Static("", id="metric-usecases", classes="metric")
                    yield Static("", id="metric-adapters", classes="metric")
                yield Label("Runtime local", classes="content-title")
                with Horizontal(id="runtime-toolbar"):
                    yield Select([], prompt="Aucun transport", id="runtime-mode")
                    yield Button("Démarrer", id="runtime-start", variant="success")
                    yield Button("Redémarrer", id="runtime-restart")
                    yield Button("Arrêter", id="runtime-stop", variant="error")
                yield Static("Inactif", id="runtime-status")
                yield RichLog(
                    id="runtime-log",
                    wrap=True,
                    markup=True,
                    max_lines=1000,
                )
            with VerticalScroll(id="project-plan"):
                yield Label("ÉTAT DU PROJET", classes="section-title")
                yield Static("", id="project-details")
                yield Label("Diagnostic", classes="content-title")
                yield Static("", id="project-doctor")
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_project)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav-new":
            self.action_new_project()
        elif event.button.id == "nav-refresh":
            self.action_refresh_project()
        elif event.button.id == "nav-guide":
            self.run_worker(self.action_classic_guide(), group="runtime-control")
        elif event.button.id == "runtime-start":
            self.action_start_runtime()
        elif event.button.id == "runtime-restart":
            self.run_worker(
                self._restart_runtime(), exclusive=True, group="runtime-control"
            )
        elif event.button.id == "runtime-stop":
            self.action_stop_runtime()

    def action_refresh_project(self) -> None:
        self._refresh_project()
        self.notify("État du projet actualisé.", title="Arclith")

    def action_new_project(self) -> None:
        if self._runtime.is_running:
            self.notify(
                "Arrêtez le runtime avant de changer de projet.", severity="warning"
            )
            return
        self.app.push_screen(
            ProjectWizardScreen(self._project_root.parent),
            self._project_created,
        )

    async def action_classic_guide(self) -> None:
        await self._runtime.stop()
        self.app.exit(self._project_root)

    def action_start_runtime(self) -> None:
        if self._runtime.is_running:
            self.notify("Un runtime est déjà actif.", severity="warning")
            return
        try:
            mode = RuntimeMode(str(self.query_one("#runtime-mode", Select).value))
            command = resolve_runtime_command(self._project_root, mode)
        except (ProjectRuntimeError, ValueError) as exc:
            self._set_runtime_status(f"[red]{escape(str(exc))}[/red]", running=False)
            return
        log = self.query_one("#runtime-log", RichLog)
        log.clear()
        log.write(f"[cyan]$ {escape(command.display())}[/cyan]")
        if command.endpoint is not None:
            log.write(f"[green]↗ {escape(command.endpoint)}[/green]")
        self._set_runtime_status(
            f"[green]● Démarrage de {escape(_RUNTIME_LABELS[mode])}…[/green]",
            running=True,
        )
        self._run_runtime(command)

    def action_stop_runtime(self) -> None:
        self.run_worker(self._stop_runtime(), exclusive=True, group="runtime-control")

    async def action_request_quit(self) -> None:
        await self._runtime.stop()
        self.app.exit()

    async def on_unmount(self) -> None:
        await self._runtime.stop()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#project-sidebar", Vertical).display = event.size.width >= 100
        self.query_one("#project-plan", VerticalScroll).display = event.size.width >= 72

    @work(exclusive=True, group="project-runtime")
    async def _run_runtime(self, command: RuntimeCommand) -> None:
        try:
            return_code = await self._runtime.run(command, self._write_runtime_line)
        except (OSError, RuntimeError) as exc:
            self.query_one("#runtime-log", RichLog).write(
                f"[red]{escape(str(exc))}[/red]"
            )
            self._set_runtime_status("[red]● Échec du runtime[/red]", running=False)
            return
        if return_code == 0:
            status = "[green]● Runtime terminé[/green]"
        elif return_code in {-2, 130}:
            status = "[yellow]■ Runtime arrêté[/yellow]"
        else:
            status = f"[red]● Runtime terminé avec le code {return_code}[/red]"
        self._set_runtime_status(status, running=False)

    async def _stop_runtime(self) -> None:
        if not self._runtime.is_running:
            return
        self.query_one("#runtime-log", RichLog).write(
            "[yellow]■ Arrêt demandé…[/yellow]"
        )
        self._set_runtime_status("[yellow]■ Arrêt en cours…[/yellow]", running=True)
        if await self._runtime.stop():
            self._set_runtime_status("[yellow]■ Runtime arrêté[/yellow]", running=False)

    async def _restart_runtime(self) -> None:
        await self._runtime.stop()
        self.action_start_runtime()

    def _write_runtime_line(self, line: str) -> None:
        self.query_one("#runtime-log", RichLog).write(Text.from_ansi(line))

    def _set_runtime_status(self, content: str, *, running: bool) -> None:
        self.query_one("#runtime-status", Static).update(content)
        self.query_one("#runtime-start", Button).disabled = running
        self.query_one("#runtime-stop", Button).disabled = not running
        self.query_one("#runtime-restart", Button).disabled = not running

    def _refresh_project(self) -> None:
        self._overview = inspect_project(self._project_root)
        overview = self._overview
        self.query_one("#project-title", Label).update(escape(overview.name))
        self.query_one("#project-summary", Static).update(
            f"[dim]{escape(str(overview.root))}[/dim]\nPackage [cyan]{escape(overview.package)}[/cyan]"
        )
        self.query_one("#project-location", Static).update(
            f"[dim]{escape(str(overview.root))}[/dim]"
        )
        self.query_one("#metric-entities", Static).update(
            f"[b]{len(overview.entities)}[/b]\n[dim]Entités[/dim]"
        )
        self.query_one("#metric-usecases", Static).update(
            f"[b]{len(overview.usecases)}[/b]\n[dim]Use cases[/dim]"
        )
        self.query_one("#metric-adapters", Static).update(
            f"[b]{len(overview.adapters)}[/b]\n[dim]Adapters[/dim]"
        )
        self.query_one("#project-details", Static).update(
            self._project_details(overview)
        )
        self.query_one("#project-doctor", Static).update(self._doctor_text(overview))
        self._refresh_runtime_choices(overview)

    def _refresh_runtime_choices(self, overview: ProjectOverview) -> None:
        modes = available_runtime_modes(overview)
        select = self.query_one("#runtime-mode", Select)
        select.set_options([(_RUNTIME_LABELS[mode], mode.value) for mode in modes])
        select.disabled = not modes
        start = self.query_one("#runtime-start", Button)
        start.disabled = not modes or self._runtime.is_running
        if modes:
            select.value = modes[0].value
        self.query_one("#runtime-stop", Button).disabled = not self._runtime.is_running
        self.query_one(
            "#runtime-restart", Button
        ).disabled = not self._runtime.is_running

    @staticmethod
    def _project_details(overview: ProjectOverview) -> str:
        entities = ", ".join(overview.entities) or "—"
        features = ", ".join(item.name for item in overview.features) or "—"
        adapters = "\n".join(f"  • {item}" for item in overview.adapters) or "  —"
        return (
            f"[dim]Entités[/dim]\n{escape(entities)}\n\n"
            f"[dim]Features[/dim]\n{escape(features)}\n\n"
            f"[dim]Adapters[/dim]\n{escape(adapters)}"
        )

    @staticmethod
    def _doctor_text(overview: ProjectOverview) -> str:
        if not overview.issues:
            return "[green]✓ Structure, manifestes et recette lisibles[/green]"
        return "\n".join(
            f"[yellow]• {escape(issue)}[/yellow]" for issue in overview.issues
        )

    def _project_created(self, root: Path | None) -> None:
        if root is not None:
            self.app.switch_screen(ProjectDashboardScreen(root))


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
