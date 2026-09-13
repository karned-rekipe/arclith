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

_STEP_NAMES = ("intent", "domain", "storage", "transport", "review")


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
        assert app.screen.query_one("#step-intent").display is True
        assert app.screen.query_one("#step-domain").display is False
        preview = str(app.screen.query_one("#plan-preview", Static).render())
        assert "5 étapes" in preview
        assert "expose-feature" in preview


@pytest.mark.asyncio
async def test_wizard_select_value_and_options_are_visible(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)
        select = wizard.query_one("#intent", Select)
        current = select.query_one("SelectCurrent")

        assert select.content_region.height == current.region.height
        assert str(current.query_one("#label", Static).render()) == "API REST CRUD"

        await pilot.press("enter")
        await pilot.pause()

        assert select.expanded is True
        assert "API&#160;REST&#160;sur&#160;mesure" in app.export_screenshot()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert select.value == ProjectIntent.API_CUSTOM.value
        assert str(current.query_one("#label", Static).render()) == (
            "API REST sur mesure"
        )

        for _ in range(2):
            wizard.query_one("#next-step", Button).press()
            await pilot.pause()
        repository = wizard.query_one("#repository", Select)
        repository_current = repository.query_one("SelectCurrent")
        assert str(repository_current.query_one("#label", Static).render()) == (
            "Mémoire — rapide et non persistant"
        )


@pytest.mark.parametrize(
    ("intent", "usecase", "repository", "port", "path"),
    [
        (ProjectIntent.API_CRUD, False, True, True, True),
        (ProjectIntent.API_CUSTOM, True, True, True, True),
        (ProjectIntent.MCP, True, True, True, False),
        (ProjectIntent.AGENT, True, True, False, False),
        (ProjectIntent.WORKER, True, True, False, False),
        (ProjectIntent.MINIMAL, False, False, False, False),
    ],
)
@pytest.mark.asyncio
async def test_wizard_reaches_every_step_for_each_intent(
    tmp_path: Path,
    intent: ProjectIntent,
    usecase: bool,
    repository: bool,
    port: bool,
    path: bool,
) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)
        wizard.query_one("#intent", Select).value = intent.value
        await pilot.pause()

        assert wizard.query_one("#usecase-field").display is usecase
        assert wizard.query_one("#repository-field").display is repository
        assert wizard.query_one("#port-field").display is port
        assert wizard.query_one("#path-field").display is path

        expected_focus = (
            "parent-dir",
            "repository" if repository else "next-step",
            "port" if port else "next-step",
            "create-project",
        )
        for expected_step in range(1, 5):
            wizard.query_one("#next-step", Button).press()
            await pilot.pause()
            assert wizard._current_step == expected_step
            assert wizard.query_one(f"#step-{_STEP_NAMES[expected_step]}").display
            assert app.focused is not None
            assert app.focused.id == expected_focus[expected_step - 1]


@pytest.mark.asyncio
async def test_wizard_creates_project_and_opens_dashboard(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)
        for expected_step in range(1, 5):
            wizard.query_one("#next-step", Button).press()
            await pilot.pause()
            assert wizard._current_step == expected_step
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
        runtime_select = app.screen.query_one("#runtime-mode", Select)
        runtime_current = runtime_select.query_one("SelectCurrent")
        assert str(runtime_current.query_one("#label", Static).render()) == (
            "API FastAPI"
        )

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
