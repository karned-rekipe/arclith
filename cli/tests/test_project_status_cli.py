import json
from pathlib import Path

from typer.testing import CliRunner

from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import NewProjectAnswers, ProjectIntent
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.main import app
from arclith_cli.recipe import RECIPE_FILENAME

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    plan = plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name="status-service",
            intent=ProjectIntent.MINIMAL,
            entity="Todo",
            usecase=None,
            repository=None,
            transport_port=None,
            public_path=None,
        )
    )
    return execute_project_plan(plan).root


def test_status_json_is_stable_for_automation(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = runner.invoke(
        app,
        ["status", "--dir", str(project / "src" / "status_service"), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "status-service"
    assert payload["entities"] == ["Todo"]
    assert payload["issues"] == []


def test_doctor_fails_when_recipe_is_missing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / RECIPE_FILENAME).unlink()

    result = runner.invoke(app, ["doctor", "--dir", str(project)])

    assert result.exit_code == 1
    assert "Recette absente" in result.output


def test_status_rejects_non_arclith_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Projet Arclith introuvable" in result.output
