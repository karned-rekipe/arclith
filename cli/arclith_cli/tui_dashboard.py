from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, RichLog, Select, Static

from arclith_cli.guide_models import ProjectOverview
from arclith_cli.guide_status import inspect_project
from arclith_cli.project_runtime import (
    ProjectRuntimeError,
    RuntimeCommand,
    RuntimeMode,
    available_runtime_modes,
    resolve_runtime_command,
)
from arclith_cli.tui_adapter import AddAdapterScreen
from arclith_cli.tui_project_picker import ProjectPickerScreen
from arclith_cli.tui_runtime import ManagedRuntime

_RUNTIME_LABELS = {
    RuntimeMode.API: "API FastAPI",
    RuntimeMode.MCP_HTTP: "MCP HTTP",
    RuntimeMode.MCP_SSE: "MCP SSE",
    RuntimeMode.BUS: "Worker RabbitMQ",
    RuntimeMode.ALL: "API + MCP",
}


class ProjectDashboardScreen(Screen[None]):
    """Inspect, extend and run one existing Arclith project."""

    BINDINGS = [
        ("a", "add_adapter", "Ajouter un adapter"),
        ("o", "open_project", "Ouvrir un projet"),
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
                yield Button("Ajouter un adapter", id="nav-add-adapter")
                yield Button("Ouvrir un projet", id="nav-open")
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
                yield Label("Faire évoluer", classes="content-title")
                with Horizontal(id="project-actions"):
                    yield Button(
                        "Ajouter un adapter",
                        id="project-add-adapter",
                        variant="primary",
                    )
                    yield Button("Ouvrir un autre projet", id="project-open")
                    yield Button("Guide avancé", id="project-guide")
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
        if event.button.id in {"nav-add-adapter", "project-add-adapter"}:
            self.action_add_adapter()
        elif event.button.id in {"nav-open", "project-open"}:
            self.action_open_project()
        elif event.button.id == "nav-new":
            self.action_new_project()
        elif event.button.id == "nav-refresh":
            self.action_refresh_project()
        elif event.button.id in {"nav-guide", "project-guide"}:
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
        if not self._can_mutate_project("changer de projet"):
            return
        # Lazy import keeps app composition and dashboard modules acyclic.
        from arclith_cli.tui import ProjectWizardScreen

        self.app.push_screen(
            ProjectWizardScreen(self._project_root.parent),
            self._project_created,
        )

    def action_open_project(self) -> None:
        if not self._can_mutate_project("changer de projet"):
            return
        self.app.push_screen(
            ProjectPickerScreen(self._project_root.parent),
            self._project_opened,
        )

    def action_add_adapter(self) -> None:
        if not self._can_mutate_project("modifier le projet"):
            return
        overview = self._overview or inspect_project(self._project_root)
        self.app.push_screen(
            AddAdapterScreen(self._project_root, overview.adapters),
            self._adapter_added,
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
            f"[dim]{escape(str(overview.root))}[/dim]\n"
            f"Package [cyan]{escape(overview.package)}[/cyan]"
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

    def _project_opened(self, root: Path | None) -> None:
        if root is not None and root != self._project_root:
            self.app.switch_screen(ProjectDashboardScreen(root))

    def _adapter_added(self, adapter_key: str | None) -> None:
        if adapter_key is not None:
            self._refresh_project()

    def _can_mutate_project(self, operation: str) -> bool:
        if not self._runtime.is_running:
            return True
        self.notify(
            f"Arrêtez le runtime avant de {operation}.",
            severity="warning",
        )
        return False
