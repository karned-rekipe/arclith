import re
import stat
from pathlib import Path

import pytest
import typer

from arclith_cli.core_scaffold import (
    add_entity_cmd,
    add_intent_interpreter_cmd,
    add_usecase_cmd,
)
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.init_project import init_project_cmd


def _src_project(tmp_path: Path, package_name: str = "demo_service") -> Path:
    project_dir = tmp_path / "demo-service"
    package_root = project_dir / "src" / package_name
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo-service"\n', encoding="utf-8"
    )
    return project_dir


def test_add_entity_creates_guided_entity_in_src_package(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_entity_cmd(project_dir=project_dir, entity_name="ShoppingItem")

    assert (
        generated
        == project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "models"
        / "shopping_item.py"
    )
    content = generated.read_text(encoding="utf-8")
    assert content.startswith("from __future__ import annotations\n")
    assert "from arclith.domain.models.entity import Entity" in content
    assert "class ShoppingItem(Entity):" in content
    assert "TODO: define the business fields and invariants" in content
    assert "docs/tutorials/todo-list/02-create-entity.md" in content
    assert "docs.pydantic.dev/latest/concepts/validators/" in content
    assert "from pydantic import Field" not in content
    assert (project_dir / "src" / "demo_service" / "domain" / "__init__.py").exists()
    assert (
        project_dir / "src" / "demo_service" / "domain" / "models" / "__init__.py"
    ).exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_init_project_creates_minimal_src_layout_without_entity(tmp_path: Path) -> None:
    generated = init_project_cmd(project_name="todo-list-service", directory=tmp_path)

    package_root = generated / "src" / "todo_list_service"
    assert generated == tmp_path / "todo-list-service"
    assert (generated / "pyproject.toml").exists()
    assert (generated / "main.py").exists()
    assert (generated / "Dockerfile").exists()
    assert (generated / ".dockerignore").exists()
    assert (generated / "arclith-run").exists()
    assert (generated / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    ) == ("logger: console\nrepository: memory\nobservability:\n  enabled: []\n")
    assert "arclith[fastapi,mcp]>=0.24.0" in (generated / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert (package_root / "domain" / "models" / "__init__.py").exists()
    assert (package_root / "domain" / "ports" / "inbound" / "__init__.py").exists()
    assert (package_root / "domain" / "ports" / "outbound" / "__init__.py").exists()
    assert (package_root / "application" / "use_cases" / "__init__.py").exists()
    assert (package_root / "adapters" / "inbound" / "__init__.py").exists()
    assert (package_root / "infrastructure" / "containers" / "__init__.py").exists()
    assert sorted(
        path.name for path in (package_root / "domain" / "models").glob("*.py")
    ) == ["__init__.py"]

    dockerfile = (generated / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (generated / ".dockerignore").read_text(encoding="utf-8")
    main = (generated / "main.py").read_text(encoding="utf-8")
    arclith_run = generated / "arclith-run"
    entrypoint = arclith_run.read_text(encoding="utf-8")
    assert "FROM python:3.13-slim-bookworm AS builder" in dockerfile
    assert "FROM python:3.13-slim-bookworm AS runtime" in dockerfile
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "USER 1001:1001" in dockerfile
    assert 'ENTRYPOINT ["./arclith-run"]' in dockerfile
    assert 'CMD ["api"]' in dockerfile
    assert "MODE=api" not in dockerfile
    assert "LANGGRAPH_PORT=2024" in dockerfile
    assert (
        re.search(r"(?m)^ARG .*SECRET|^ARG .*TOKEN|^ARG .*PASSWORD", dockerfile) is None
    )
    assert ".env" in dockerignore
    assert "secrets.yaml" in dockerignore
    assert "id_rsa" in dockerignore
    assert 'if [ -n "${ARCLITH_RUNTIME_MODE:-}" ]; then' in entrypoint
    assert (
        "api|mcp|mcp_http|mcp_sse|bus|command_bus|command-bus|agent|all) shift ;;"
        in entrypoint
    )
    assert "bus|command_bus|command-bus)" in entrypoint
    assert "langgraph dev" in entrypoint
    assert '"${ARCLITH_AGENT_RUNTIME:-development}" = "durable"' in entrypoint
    assert "exec arclith-agent-runtime" in entrypoint
    assert '_VALID_MODES = {"api", "mcp_http", "mcp_sse", "all"}' in main
    assert (
        'arclith.run_with_probes(_run_api, _run_mcp_http, transports=["api", "mcp_http"])'
        in main
    )
    assert arclith_run.stat().st_mode & stat.S_IXUSR


def test_init_project_refuses_existing_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "todo-list-service"
    project_dir.mkdir()

    with pytest.raises(typer.Exit):
        init_project_cmd(project_name="todo-list-service", directory=tmp_path)


def test_add_usecase_defaults_to_guided_transverse_usecase_for_python_callers(
    tmp_path: Path,
) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(
        project_dir=project_dir, usecase_name="PlanShoppingList"
    )

    assert (
        generated
        == project_dir
        / "src"
        / "demo_service"
        / "application"
        / "use_cases"
        / "plan_shopping_list.py"
    )
    inbound_port = (
        project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "ports"
        / "inbound"
        / "plan_shopping_list.py"
    )
    inbound_content = inbound_port.read_text(encoding="utf-8")
    usecase_content = generated.read_text(encoding="utf-8")
    assert "class PlanShoppingListCommand(BaseModel):" in inbound_content
    assert "class PlanShoppingListResult(BaseModel):" in inbound_content
    assert (
        "async def execute(self, command: PlanShoppingListCommand) -> PlanShoppingListResult:"
        in inbound_content
    )
    assert "docs/tutorials/todo-list/03-create-usecase.md" in inbound_content
    assert "class PlanShoppingListUseCase(PlanShoppingListPort):" in usecase_content
    assert "Repository" not in usecase_content
    assert (project_dir / "src" / "demo_service" / "domain" / "__init__.py").exists()
    assert (
        project_dir / "src" / "demo_service" / "domain" / "ports" / "__init__.py"
    ).exists()
    assert (
        project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "ports"
        / "inbound"
        / "__init__.py"
    ).exists()
    assert (
        project_dir / "src" / "demo_service" / "application" / "__init__.py"
    ).exists()
    assert (
        project_dir
        / "src"
        / "demo_service"
        / "application"
        / "use_cases"
        / "__init__.py"
    ).exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_add_intent_interpreter_creates_minimal_interpreter_in_src_package(
    tmp_path: Path,
) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_intent_interpreter_cmd(
        project_dir=project_dir, intent_name="IngredientIntent"
    )

    assert generated == (
        project_dir
        / "src"
        / "demo_service"
        / "application"
        / "intent_interpreters"
        / "ingredient_intent.py"
    )
    assert generated.read_text(encoding="utf-8") == (
        "class IngredientIntentInterpreter:\n"
        "    async def interpret(self, prompt: str) -> None:\n"
        '        raise NotImplementedError("Implement IngredientIntentInterpreter.interpret")\n'
    )
    assert (
        project_dir / "src" / "demo_service" / "application" / "__init__.py"
    ).exists()
    assert (
        project_dir
        / "src"
        / "demo_service"
        / "application"
        / "intent_interpreters"
        / "__init__.py"
    ).exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_add_usecase_strips_repeated_usecase_suffix(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(
        project_dir=project_dir, usecase_name="plan-shopping-list-use-case-usecase"
    )

    assert generated.name == "plan_shopping_list.py"
    assert (
        "class PlanShoppingListUseCase(PlanShoppingListPort):"
        in generated.read_text(encoding="utf-8")
    )
    assert "class PlanShoppingListPort(ABC):" in (
        project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "ports"
        / "inbound"
        / "plan_shopping_list.py"
    ).read_text(encoding="utf-8")
    assert "UseCaseUseCase" not in generated.read_text(encoding="utf-8")


def test_add_usecase_links_existing_entity_with_typed_repository(
    tmp_path: Path,
) -> None:
    project_dir = _src_project(tmp_path)
    add_entity_cmd(project_dir=project_dir, entity_name="Todo")

    generated = add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateTodo",
        entity_name="Todo",
    )

    inbound_port = project_dir / "src/demo_service/domain/ports/inbound/create_todo.py"
    inbound_content = inbound_port.read_text(encoding="utf-8")
    usecase_content = generated.read_text(encoding="utf-8")
    assert "from demo_service.domain.models.todo import Todo" in inbound_content
    assert "class CreateTodoCommand(BaseModel):" in inbound_content
    assert (
        "async def execute(self, command: CreateTodoCommand) -> Todo:"
        in inbound_content
    )
    assert (
        "from arclith.domain.ports.outbound.repository import Repository"
        in usecase_content
    )
    assert (
        "def __init__(self, repository: Repository[Todo]) -> None:" in usecase_content
    )
    assert (
        "async def execute(self, command: CreateTodoCommand) -> Todo:"
        in usecase_content
    )


def test_add_usecase_uses_detected_entity_filename_for_import(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)
    entity_file = project_dir / "src/demo_service/domain/models/work_item.py"
    entity_file.parent.mkdir(parents=True)
    entity_file.write_text(
        "from arclith.domain.models.entity import Entity\n\nclass Todo(Entity):\n    pass\n",
        encoding="utf-8",
    )

    generated = add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateTodo",
        entity_name="Todo",
    )

    assert (
        "from demo_service.domain.models.work_item import Todo"
        in generated.read_text(encoding="utf-8")
    )


def test_add_usecase_existing_entity_reuses_ast_scanner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)
    entity_file = project_dir / "src/demo_service/domain/models/todo.py"
    calls: list[Path] = []

    def fake_scan_entities(scanned_project: Path) -> list[EntityInfo]:
        calls.append(scanned_project)
        return [EntityInfo(pascal="Todo", snake="todo", file_path=entity_file)]

    monkeypatch.setattr(
        "arclith_cli.core_scaffold.scan_entities",
        fake_scan_entities,
    )

    add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateTodo",
        entity_name="Todo",
    )

    assert calls == [project_dir]


def test_add_usecase_rejects_missing_existing_entity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _src_project(tmp_path)
    calls: list[Path] = []

    def fake_scan_entities(scanned_project: Path) -> list[EntityInfo]:
        calls.append(scanned_project)
        return [
            EntityInfo(
                pascal="Existing",
                snake="existing",
                file_path=project_dir / "src/demo_service/domain/models/existing.py",
            )
        ]

    monkeypatch.setattr(
        "arclith_cli.core_scaffold.scan_entities",
        fake_scan_entities,
    )

    with pytest.raises(typer.Exit):
        add_usecase_cmd(
            project_dir=project_dir,
            usecase_name="CreateTodo",
            entity_name="Missing",
        )

    output = capsys.readouterr().out
    assert "Entité introuvable" in output
    assert "Entités détectées : Existing" in output
    assert "--new-entity Missing" in output
    assert calls == [project_dir]
    assert not (
        project_dir / "src/demo_service/application/use_cases/create_todo.py"
    ).exists()


def test_add_usecase_new_entity_creates_and_links_entity(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateTodo",
        new_entity_name="Todo",
    )

    entity_file = project_dir / "src/demo_service/domain/models/todo.py"
    assert "class Todo(Entity):" in entity_file.read_text(encoding="utf-8")
    assert "Repository[Todo]" in generated.read_text(encoding="utf-8")


def test_add_usecase_new_entity_reuses_matching_existing_entity(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)
    entity_file = add_entity_cmd(project_dir=project_dir, entity_name="Todo")
    original = entity_file.read_text(encoding="utf-8")

    generated = add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateTodo",
        new_entity_name="Todo",
    )

    assert entity_file.read_text(encoding="utf-8") == original
    assert "Repository[Todo]" in generated.read_text(encoding="utf-8")


def test_add_usecase_new_entity_rejects_mismatched_existing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_dir = _src_project(tmp_path)
    entity_file = project_dir / "src/demo_service/domain/models/todo.py"
    entity_file.parent.mkdir(parents=True)
    entity_file.write_text("class SomethingElse:\n    pass\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        add_usecase_cmd(
            project_dir=project_dir,
            usecase_name="CreateTodo",
            new_entity_name="Todo",
        )

    output = capsys.readouterr().out
    assert "existe mais ne déclare pas" in output
    assert "class Todo(Entity)" in output
    assert entity_file.read_text(encoding="utf-8") == "class SomethingElse:\n    pass\n"


def test_add_usecase_rejects_two_entity_modes(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_usecase_cmd(
            project_dir=project_dir,
            usecase_name="CreateTodo",
            entity_name="Todo",
            new_entity_name="Todo",
        )


def test_add_intent_interpreter_strips_repeated_interpreter_suffix(
    tmp_path: Path,
) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_intent_interpreter_cmd(
        project_dir=project_dir,
        intent_name="ingredient-intent-interpreter-interpreter",
    )

    assert generated.name == "ingredient_intent.py"
    assert "class IngredientIntentInterpreter:" in generated.read_text(encoding="utf-8")
    assert "InterpreterInterpreter" not in generated.read_text(encoding="utf-8")


def test_add_entity_supports_legacy_root_layout(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy-service"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "legacy-service"\n', encoding="utf-8"
    )

    generated = add_entity_cmd(project_dir=project_dir, entity_name="Recipe")

    assert generated == project_dir / "domain" / "models" / "recipe.py"
    assert (project_dir / "domain" / "__init__.py").exists()
    assert (project_dir / "domain" / "models" / "__init__.py").exists()
    assert not (project_dir / "__init__.py").exists()


def test_add_usecase_supports_legacy_root_layout(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy-service"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "legacy-service"\n', encoding="utf-8"
    )

    add_entity_cmd(project_dir=project_dir, entity_name="Recipe")
    generated = add_usecase_cmd(
        project_dir=project_dir,
        usecase_name="CreateRecipe",
        entity_name="Recipe",
    )

    assert generated == project_dir / "application" / "use_cases" / "create_recipe.py"
    assert (
        "from domain.ports.inbound.create_recipe import CreateRecipeCommand, CreateRecipePort\n"
        in generated.read_text(encoding="utf-8")
    )
    assert "from domain.models.recipe import Recipe" in generated.read_text(
        encoding="utf-8"
    )
    assert (project_dir / "domain" / "ports" / "inbound" / "create_recipe.py").exists()
    assert (project_dir / "domain" / "ports" / "inbound" / "__init__.py").exists()
    assert not (project_dir / "__init__.py").exists()


def test_add_entity_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)
    existing = project_dir / "src" / "demo_service" / "domain" / "models" / "recipe.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("class Recipe:\n    pass\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        add_entity_cmd(project_dir=project_dir, entity_name="Recipe")

    assert existing.read_text(encoding="utf-8") == "class Recipe:\n    pass\n"


def test_add_usecase_rejects_invalid_name(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_usecase_cmd(project_dir=project_dir, usecase_name="123-import")


def test_add_usecase_refuses_to_overwrite_existing_inbound_port(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)
    existing = (
        project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "ports"
        / "inbound"
        / "recipe.py"
    )
    existing.parent.mkdir(parents=True)
    existing.write_text("class RecipePort:\n    pass\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        add_usecase_cmd(project_dir=project_dir, usecase_name="Recipe")

    assert existing.read_text(encoding="utf-8") == "class RecipePort:\n    pass\n"
    assert not (
        project_dir / "src" / "demo_service" / "application" / "use_cases" / "recipe.py"
    ).exists()


def test_add_usecase_refuses_existing_port_before_creating_new_entity(
    tmp_path: Path,
) -> None:
    project_dir = _src_project(tmp_path)
    existing = (
        project_dir
        / "src"
        / "demo_service"
        / "domain"
        / "ports"
        / "inbound"
        / "create_todo.py"
    )
    existing.parent.mkdir(parents=True)
    existing.write_text("class CreateTodoPort:\n    pass\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        add_usecase_cmd(
            project_dir=project_dir,
            usecase_name="CreateTodo",
            new_entity_name="Todo",
        )

    assert not (project_dir / "src/demo_service/domain/models/todo.py").exists()


def test_add_intent_interpreter_rejects_invalid_name(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_intent_interpreter_cmd(project_dir=project_dir, intent_name="123-intent")
