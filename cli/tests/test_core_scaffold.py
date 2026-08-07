from pathlib import Path

import pytest
import typer

from arclith_cli.core_scaffold import add_entity_cmd, add_planner_cmd, add_usecase_cmd
from arclith_cli.init_project import init_project_cmd


def _src_project(tmp_path: Path, package_name: str = "demo_service") -> Path:
    project_dir = tmp_path / "demo-service"
    package_root = project_dir / "src" / package_name
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text('[project]\nname = "demo-service"\n', encoding="utf-8")
    return project_dir


def test_add_entity_creates_minimal_entity_in_src_package(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_entity_cmd(project_dir=project_dir, entity_name="ShoppingItem")

    assert generated == project_dir / "src" / "demo_service" / "domain" / "models" / "shopping_item.py"
    assert generated.read_text(encoding="utf-8") == (
        "from arclith.domain.models.entity import Entity\n"
        "\n"
        "\n"
        "class ShoppingItem(Entity):\n"
        "    pass\n"
    )
    assert (project_dir / "src" / "demo_service" / "domain" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "domain" / "models" / "__init__.py").exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_init_project_creates_minimal_src_layout_without_entity(tmp_path: Path) -> None:
    generated = init_project_cmd(project_name="todo-list-service", directory=tmp_path)

    package_root = generated / "src" / "todo_list_service"
    assert generated == tmp_path / "todo-list-service"
    assert (generated / "pyproject.toml").exists()
    assert (generated / "main.py").exists()
    assert (generated / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8") == (
        "logger: console\n"
        "repository: memory\n"
        "observability: none\n"
    )
    assert (package_root / "domain" / "models" / "__init__.py").exists()
    assert (package_root / "domain" / "ports" / "inbound" / "__init__.py").exists()
    assert (package_root / "domain" / "ports" / "outbound" / "__init__.py").exists()
    assert (package_root / "application" / "use_cases" / "__init__.py").exists()
    assert (package_root / "adapters" / "inbound" / "__init__.py").exists()
    assert (package_root / "infrastructure" / "containers" / "__init__.py").exists()
    assert sorted(path.name for path in (package_root / "domain" / "models").glob("*.py")) == ["__init__.py"]


def test_init_project_refuses_existing_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "todo-list-service"
    project_dir.mkdir()

    with pytest.raises(typer.Exit):
        init_project_cmd(project_name="todo-list-service", directory=tmp_path)


def test_add_usecase_creates_minimal_usecase_in_src_package(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(project_dir=project_dir, usecase_name="PlanShoppingList")

    assert generated == project_dir / "src" / "demo_service" / "application" / "use_cases" / "plan_shopping_list.py"
    inbound_port = project_dir / "src" / "demo_service" / "domain" / "ports" / "inbound" / "plan_shopping_list.py"
    assert inbound_port.read_text(encoding="utf-8") == (
        "from abc import ABC, abstractmethod\n"
        "\n"
        "\n"
        "class PlanShoppingListPort(ABC):\n"
        "    @abstractmethod\n"
        "    async def execute(self) -> None:\n"
        "        raise NotImplementedError\n"
    )
    assert generated.read_text(encoding="utf-8") == (
        "from demo_service.domain.ports.inbound.plan_shopping_list import PlanShoppingListPort\n"
        "\n"
        "\n"
        "class PlanShoppingListUseCase(PlanShoppingListPort):\n"
        "    async def execute(self) -> None:\n"
        '        raise NotImplementedError("Implement PlanShoppingListUseCase.execute")\n'
    )
    assert (project_dir / "src" / "demo_service" / "domain" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "domain" / "ports" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "domain" / "ports" / "inbound" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "application" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "application" / "use_cases" / "__init__.py").exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_add_planner_creates_minimal_planner_in_src_package(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_planner_cmd(project_dir=project_dir, planner_name="IngredientIntent")

    assert generated == project_dir / "src" / "demo_service" / "application" / "planners" / "ingredient_intent.py"
    assert generated.read_text(encoding="utf-8") == (
        "class IngredientIntentPlanner:\n"
        "    async def plan(self, prompt: str) -> None:\n"
        '        raise NotImplementedError("Implement IngredientIntentPlanner.plan")\n'
    )
    assert (project_dir / "src" / "demo_service" / "application" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "application" / "planners" / "__init__.py").exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_add_usecase_strips_repeated_usecase_suffix(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(project_dir=project_dir, usecase_name="plan-shopping-list-use-case-usecase")

    assert generated.name == "plan_shopping_list.py"
    assert "class PlanShoppingListUseCase(PlanShoppingListPort):" in generated.read_text(encoding="utf-8")
    assert (
        "class PlanShoppingListPort(ABC):"
        in (
            project_dir / "src" / "demo_service" / "domain" / "ports" / "inbound" / "plan_shopping_list.py"
        ).read_text(encoding="utf-8")
    )
    assert "UseCaseUseCase" not in generated.read_text(encoding="utf-8")


def test_add_planner_strips_repeated_planner_suffix(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_planner_cmd(project_dir=project_dir, planner_name="ingredient-intent-planner-planner")

    assert generated.name == "ingredient_intent.py"
    assert "class IngredientIntentPlanner:" in generated.read_text(encoding="utf-8")
    assert "PlannerPlanner" not in generated.read_text(encoding="utf-8")


def test_add_entity_supports_legacy_root_layout(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy-service"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text('[project]\nname = "legacy-service"\n', encoding="utf-8")

    generated = add_entity_cmd(project_dir=project_dir, entity_name="Recipe")

    assert generated == project_dir / "domain" / "models" / "recipe.py"
    assert (project_dir / "domain" / "__init__.py").exists()
    assert (project_dir / "domain" / "models" / "__init__.py").exists()
    assert not (project_dir / "__init__.py").exists()


def test_add_usecase_supports_legacy_root_layout(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy-service"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text('[project]\nname = "legacy-service"\n', encoding="utf-8")

    generated = add_usecase_cmd(project_dir=project_dir, usecase_name="CreateRecipe")

    assert generated == project_dir / "application" / "use_cases" / "create_recipe.py"
    assert (
        "from domain.ports.inbound.create_recipe import CreateRecipePort\n"
        in generated.read_text(encoding="utf-8")
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
    existing = project_dir / "src" / "demo_service" / "domain" / "ports" / "inbound" / "recipe.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("class RecipePort:\n    pass\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        add_usecase_cmd(project_dir=project_dir, usecase_name="Recipe")

    assert existing.read_text(encoding="utf-8") == "class RecipePort:\n    pass\n"
    assert not (project_dir / "src" / "demo_service" / "application" / "use_cases" / "recipe.py").exists()


def test_add_planner_rejects_invalid_name(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_planner_cmd(project_dir=project_dir, planner_name="123-planner")
