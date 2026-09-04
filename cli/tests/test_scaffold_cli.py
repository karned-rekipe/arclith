from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.main import app
from arclith_cli.recipe import RECIPE_FILENAME, load_recipe

runner = CliRunner()


def _src_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "demo-service"
    package_root = project_dir / "src" / "demo_service"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo-service"\n',
        encoding="utf-8",
    )
    return project_dir


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    arguments: list[str],
    *,
    input_text: str | None = None,
):
    monkeypatch.chdir(project_dir)
    return runner.invoke(app, arguments, input=input_text)


def test_add_usecase_entity_option_generates_linked_scaffold_and_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)
    add_entity_cmd(project_dir=project_dir, entity_name="Todo")

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo", "--entity", "Todo"],
    )

    assert result.exit_code == 0, result.output
    generated = project_dir / "src/demo_service/application/use_cases/create_todo.py"
    assert "Repository[Todo]" in generated.read_text(encoding="utf-8")
    assert load_recipe(project_dir / RECIPE_FILENAME).steps[-1].args == {
        "usecase": "CreateTodo",
        "entity": "Todo",
        "new_entity": None,
        "no_entity": False,
    }


def test_add_usecase_new_entity_option_creates_both_scaffolds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo", "--new-entity", "Todo"],
    )

    assert result.exit_code == 0, result.output
    assert (project_dir / "src/demo_service/domain/models/todo.py").exists()
    assert (
        project_dir / "src/demo_service/application/use_cases/create_todo.py"
    ).exists()


def test_add_usecase_no_entity_option_generates_transverse_scaffold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "RunMaintenance", "--no-entity"],
    )

    assert result.exit_code == 0, result.output
    generated = (
        project_dir / "src/demo_service/application/use_cases/run_maintenance.py"
    )
    assert "RunMaintenanceResult" in generated.read_text(encoding="utf-8")
    assert "Repository" not in generated.read_text(encoding="utf-8")


def test_add_usecase_options_are_mutually_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo", "--entity", "Todo", "--no-entity"],
    )

    assert result.exit_code == 1
    assert "mutuellement" in result.output
    assert "exclusives" in result.output


def test_add_usecase_interactive_selects_detected_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)
    add_entity_cmd(project_dir=project_dir, entity_name="Todo")

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo"],
        input_text="1\n",
    )

    assert result.exit_code == 0, result.output
    assert "Todo" in result.output
    generated = project_dir / "src/demo_service/application/use_cases/create_todo.py"
    assert "Repository[Todo]" in generated.read_text(encoding="utf-8")


def test_add_usecase_interactive_can_create_entity_when_none_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo"],
        input_text="1\nTodo\n",
    )

    assert result.exit_code == 0, result.output
    assert "Aucune entité détectée" in result.output
    assert (project_dir / "src/demo_service/domain/models/todo.py").exists()


def test_add_usecase_interactive_can_create_another_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)
    add_entity_cmd(project_dir=project_dir, entity_name="Todo")

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateShoppingItem"],
        input_text="2\nShoppingItem\n",
    )

    assert result.exit_code == 0, result.output
    assert (project_dir / "src/demo_service/domain/models/shopping_item.py").exists()
    generated = (
        project_dir / "src/demo_service/application/use_cases/create_shopping_item.py"
    )
    assert "Repository[ShoppingItem]" in generated.read_text(encoding="utf-8")


def test_add_usecase_interactive_can_continue_without_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "RunMaintenance"],
        input_text="2\n",
    )

    assert result.exit_code == 0, result.output
    generated = (
        project_dir / "src/demo_service/application/use_cases/run_maintenance.py"
    )
    assert "Repository" not in generated.read_text(encoding="utf-8")


def test_add_usecase_interactive_can_cancel_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project_dir,
        ["add-usecase", "CreateTodo"],
        input_text="3\n",
    )

    assert result.exit_code == 0, result.output
    assert "Création annulée" in result.output
    assert not (
        project_dir / "src/demo_service/application/use_cases/create_todo.py"
    ).exists()
    assert not (project_dir / RECIPE_FILENAME).exists()
