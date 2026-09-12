from pathlib import Path

import pytest
from textual.widgets import Button, Select, Static

from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    NewProjectAnswers,
    ProjectIntent,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.tui import (
    ArclithTui,
    ProjectDashboardScreen,
    ProjectWizardScreen,
    WelcomeScreen,
)
from arclith_cli.project_runtime import RuntimeCommand
from arclith_cli.tui_runtime import ManagedRuntime, RuntimeLineSink


def _api_project(tmp_path: Path) -> Path:
    return execute_project_plan(
        plan_new_project(
            NewProjectAnswers(
                parent_dir=tmp_path,
                project_name="tui-service",
                intent=ProjectIntent.API_CRUD,
                entity="Product",
                usecase=None,
                repository=RepositoryChoice.MEMORY,
                transport_port=8765,
                public_path="/v1/products",
            )
        )
    ).root


@pytest.mark.asyncio
async def test_tui_opens_welcome_then_project_wizard(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WelcomeScreen)

        await pilot.press("n")
        await pilot.pause()

        assert isinstance(app.screen, ProjectWizardScreen)
        preview = str(app.screen.query_one("#plan-preview", Static).render())
        assert "5 étapes" in preview
        assert "expose-feature" in preview


@pytest.mark.asyncio
async def test_wizard_creates_project_and_opens_dashboard(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)
        wizard.query_one("#create-project", Button).press()
        for _ in range(100):
            await pilot.pause(0.05)
            if isinstance(app.screen, ProjectDashboardScreen):
                break
        await pilot.pause()

        assert isinstance(app.screen, ProjectDashboardScreen)
        assert (tmp_path / "catalog-service/arclith.recipe.yaml").is_file()
        assert app.screen.query_one("#runtime-mode", Select).value == "api"


@pytest.mark.asyncio
async def test_wizard_cannot_close_during_atomic_generation(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)
        wizard._set_busy(True)

        await pilot.press("escape")
        await pilot.pause()

        assert app.screen is wizard


@pytest.mark.asyncio
async def test_dashboard_discovers_runtime_and_streams_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _api_project(tmp_path)

    async def fake_run(
        self: ManagedRuntime,
        _command: RuntimeCommand,
        on_line: RuntimeLineSink,
    ) -> int:
        del self, _command
        on_line("Application startup complete")
        return 0

    monkeypatch.setattr(ManagedRuntime, "run", fake_run)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProjectDashboardScreen)

        await pilot.press("s")
        for _ in range(20):
            await pilot.pause(0.05)
            status = str(app.screen.query_one("#runtime-status", Static).render())
            if "terminé" in status:
                break

        assert "Runtime terminé" in status


@pytest.mark.asyncio
async def test_dashboard_hides_secondary_panels_in_narrow_terminal(
    tmp_path: Path,
) -> None:
    app = ArclithTui(_api_project(tmp_path))

    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()

        assert app.screen.query_one("#project-sidebar").display is False
        assert app.screen.query_one("#project-plan").display is False


@pytest.mark.asyncio
async def test_dashboard_restores_controls_after_runtime_stop(
    tmp_path: Path,
) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dashboard = app.screen
        assert isinstance(dashboard, ProjectDashboardScreen)
        dashboard._runtime = _RuntimeStub()  # type: ignore[assignment]

        await dashboard._stop_runtime()

        assert dashboard.query_one("#runtime-start", Button).disabled is False
        assert dashboard.query_one("#runtime-stop", Button).disabled is True
        status = str(dashboard.query_one("#runtime-status", Static).render())
        assert "Runtime arrêté" in status


class _RuntimeStub:
    is_running = True

    async def stop(self) -> bool:
        self.is_running = False
        return True
