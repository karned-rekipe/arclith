from pathlib import Path

import pytest
import yaml
from textual.widgets import Button, Input, Select, Static, Switch

from arclith_cli.capabilities import get_capability
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
from arclith_cli.tui_adapter import AddAdapterScreen
from arclith_cli.tui_adapter_catalog import (
    AdapterInstallRequest,
    available_adapters,
    configuration_replacements,
)
from arclith_cli.tui_project_picker import ProjectPickerScreen
from arclith_cli.recipe import load_recipe
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
async def test_welcome_opens_an_existing_project_with_picker(tmp_path: Path) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

        picker = app.screen
        assert isinstance(picker, ProjectPickerScreen)
        picker.query_one("#picker-path", Input).value = str(project / "src")
        await pilot.pause()
        assert picker.query_one("#picker-open", Button).disabled is False

        picker.query_one("#picker-open", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, ProjectDashboardScreen)
        assert app.screen._project_root == project


@pytest.mark.asyncio
async def test_project_picker_rejects_a_non_arclith_directory(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("o")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ProjectPickerScreen)

        picker.query_one("#picker-path", Input).value = str(tmp_path / "missing")
        await pilot.pause()

        assert picker.query_one("#picker-open", Button).disabled is True
        status = str(picker.query_one("#picker-status", Static).render())
        assert "introuvable" in status


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


@pytest.mark.asyncio
async def test_wizard_domain_fields_accept_keyboard_input(tmp_path: Path) -> None:
    app = ArclithTui(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        wizard = app.screen
        assert isinstance(wizard, ProjectWizardScreen)

        wizard.query_one("#next-step", Button).press()
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "parent-dir"

        project_name = wizard.query_one("#project-name", Input)
        project_name.value = ""
        project_name.focus()
        await pilot.press(*"api-service")
        assert project_name.value == "api-service"

        entity = wizard.query_one("#entity", Input)
        entity.value = ""
        await pilot.press("tab", *"Order")
        assert app.focused is entity
        assert entity.value == "Order"


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
async def test_dashboard_opens_catalog_without_installed_adapters(
    tmp_path: Path,
) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, AddAdapterScreen)
        capability = screen.query_one("#adapter-capability", Select)
        adapter = screen.query_one("#adapter-choice", Select)
        assert capability.value == "repository"
        assert adapter.value == "mongodb"
        repository = get_capability("repository")
        assert repository is not None
        assert "memory" not in {
            item.name
            for item in available_adapters(
                repository,
                frozenset({"repository/memory"}),
            )
        }
        assert screen.query_one("#adapter-param-0", Input).value == project.name
        assert screen.query_one("#adapter-activate", Switch).value is False
        preview = str(screen.query_one("#adapter-command", Static).render())
        assert "repository" in preview
        assert "mongodb" in preview
        assert "--no-activate" in preview


@pytest.mark.asyncio
async def test_dashboard_installs_an_additional_repository_and_records_it(
    tmp_path: Path,
) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AddAdapterScreen)

        screen.query_one("#adapter-install", Button).press()
        for _ in range(100):
            await pilot.pause(0.05)
            if isinstance(app.screen, ProjectDashboardScreen):
                break

        assert isinstance(app.screen, ProjectDashboardScreen)
        manifest = project / ".arclith/blueprints/repository-mongodb.yaml"
        assert manifest.is_file()
        adapters = yaml.safe_load(
            (project / "config/adapters/adapters.yaml").read_text(encoding="utf-8")
        )
        assert adapters["repository"] == "memory"
        assert app.screen._overview is not None
        assert "repository/mongodb" in app.screen._overview.adapters
        recipe = load_recipe(project / "arclith.recipe.yaml")
        assert recipe.steps[-1].command == "add-adapter"
        assert recipe.steps[-1].args["adapter"] == "mongodb"


def test_adapter_command_redacts_secret_values(tmp_path: Path) -> None:
    capability = get_capability("llm")
    assert capability is not None
    adapter = capability.get_adapter("openai")
    assert adapter is not None
    request = AdapterInstallRequest(
        project_root=tmp_path,
        capability=capability,
        adapter=adapter,
        parameters=(("api_key", "super-secret"),),
        profile=None,
        activate=False,
    )

    command = request.command()

    assert "super-secret" not in command
    assert "api_key=<redacted>" in command


def test_catalog_warns_when_an_adapter_replaces_shared_config() -> None:
    storage = get_capability("storage")
    assert storage is not None
    s3 = storage.get_adapter("s3")
    assert s3 is not None

    replacements = configuration_replacements(
        s3,
        frozenset({"storage/filesystem"}),
    )

    assert replacements == ("storage/filesystem",)


@pytest.mark.asyncio
async def test_dashboard_can_switch_to_another_existing_project(tmp_path: Path) -> None:
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    first = _api_project(first_parent)
    second = _api_project(second_parent)
    app = ArclithTui(first)

    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ProjectPickerScreen)
        picker.query_one("#picker-path", Input).value = str(second)
        await pilot.pause()
        picker.query_one("#picker-open", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, ProjectDashboardScreen)
        assert app.screen._project_root == second


@pytest.mark.asyncio
async def test_adapter_profile_updates_generated_parameter_fields(
    tmp_path: Path,
) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AddAdapterScreen)

        screen.query_one("#adapter-capability", Select).value = "observability"
        await pilot.pause()
        assert screen.query_one("#adapter-choice", Select).value == "langsmith"
        profile = screen.query_one("#adapter-profile", Select)
        assert profile.display is True

        profile.value = "production"
        await pilot.pause()

        sampling = screen._parameter_widgets["sampling_rate"]
        capture_inputs = screen._parameter_widgets["capture_inputs"]
        assert isinstance(sampling, Input)
        assert sampling.value == "0.1"
        assert isinstance(capture_inputs, Switch)
        assert capture_inputs.value is False
        assert screen.query_one("#adapter-activate", Switch).value is True


@pytest.mark.asyncio
async def test_adapter_prerequisite_error_keeps_catalog_open(tmp_path: Path) -> None:
    project = _api_project(tmp_path)
    app = ArclithTui(project)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AddAdapterScreen)

        screen.query_one("#adapter-capability", Select).value = "agent-persistence"
        await pilot.pause()
        screen.query_one("#adapter-install", Button).press()
        for _ in range(40):
            await pilot.pause(0.05)
            error = str(screen.query_one("#adapter-error", Static).render())
            if "agent/langgraph" in error:
                break

        assert app.screen is screen
        assert "agent/langgraph" in error
        assert screen.query_one("#adapter-install", Button).disabled is False


@pytest.mark.asyncio
async def test_dashboard_hides_secondary_panels_in_narrow_terminal(
    tmp_path: Path,
) -> None:
    app = ArclithTui(_api_project(tmp_path))

    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()

        assert app.screen.query_one("#project-sidebar").display is False
        assert app.screen.query_one("#project-plan").display is False
        assert app.screen.query_one("#project-add-adapter", Button).display is True
        assert app.screen.query_one("#project-open", Button).display is True


@pytest.mark.asyncio
async def test_adapter_actions_remain_visible_in_narrow_terminal(
    tmp_path: Path,
) -> None:
    app = ArclithTui(_api_project(tmp_path))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AddAdapterScreen)

        assert screen.query_one("#adapter-sidebar").display is False
        install = screen.query_one("#adapter-install", Button)
        assert install.display is True
        assert install.region.height == 3


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
