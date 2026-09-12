from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    NewProjectAnswers,
    ProjectIntent,
    ProjectOverview,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.main import app
from arclith_cli.project_runtime import (
    ProjectRuntimeError,
    RuntimeCommand,
    RuntimeMode,
    available_runtime_modes,
    resolve_runtime_command,
    run_foreground,
)

runner = CliRunner()


def _api_project(tmp_path: Path) -> Path:
    plan = plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name="runtime-service",
            intent=ProjectIntent.API_CRUD,
            entity="Product",
            usecase=None,
            repository=RepositoryChoice.MEMORY,
            transport_port=8765,
            public_path="/v1/products",
        )
    )
    return execute_project_plan(plan).root


def test_available_runtime_modes_follow_installed_transports(tmp_path: Path) -> None:
    overview = ProjectOverview(
        root=tmp_path,
        name="runtime-service",
        package="runtime_service",
        entities=(),
        usecases=(),
        features=(),
        adapters=("api/fastapi", "mcp/fastmcp", "command-bus/rabbitmq"),
        issues=(),
    )

    assert available_runtime_modes(overview) == (
        RuntimeMode.API,
        RuntimeMode.MCP_HTTP,
        RuntimeMode.MCP_SSE,
        RuntimeMode.BUS,
        RuntimeMode.ALL,
    )


def test_resolve_runtime_command_uses_project_config(tmp_path: Path) -> None:
    project = _api_project(tmp_path)

    command = resolve_runtime_command(project / "src/runtime_service", RuntimeMode.API)

    assert command.root == project
    assert command.argv == ("uv", "run", "python", "main.py")
    assert command.environment == (("MODE", "api"),)
    assert command.endpoint == "http://127.0.0.1:8765"
    assert command.display() == "MODE=api uv run python main.py"


def test_resolve_runtime_command_rejects_missing_transport(tmp_path: Path) -> None:
    project = _api_project(tmp_path)

    with pytest.raises(ProjectRuntimeError, match="mcp_http.*indisponible"):
        resolve_runtime_command(project, RuntimeMode.MCP_HTTP)


def test_run_foreground_preserves_project_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    command = RuntimeCommand(
        root=tmp_path,
        project_name="runtime-service",
        mode=RuntimeMode.API,
        argv=("uv", "run", "python", "main.py"),
        environment=(("MODE", "api"),),
        endpoint="http://127.0.0.1:8000",
    )

    run_foreground(command)

    assert captured["args"] == (command.argv,)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["check"] is True
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"]["MODE"] == "api"


def test_run_command_launches_api_from_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _api_project(tmp_path)
    launched: list[RuntimeCommand] = []
    monkeypatch.setattr(
        "arclith_cli.project_runtime_cli.run_foreground",
        launched.append,
    )

    result = runner.invoke(app, ["run", "api", "--dir", str(project)])

    assert result.exit_code == 0, result.output
    assert len(launched) == 1
    assert launched[0].mode == RuntimeMode.API
    assert "runtime-service" in result.output
    assert "http://127.0.0.1:8765" in result.output
    assert "Ctrl+C" in result.output


def test_run_command_propagates_runtime_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _api_project(tmp_path)

    def fail(_command: RuntimeCommand) -> None:
        raise subprocess.CalledProcessError(7, ["uv"])

    monkeypatch.setattr("arclith_cli.project_runtime_cli.run_foreground", fail)

    result = runner.invoke(app, ["run", "api", "--dir", str(project)])

    assert result.exit_code == 7
    assert "code 7" in result.output
