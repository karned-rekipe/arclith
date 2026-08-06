from pathlib import Path

import pytest
import typer

from arclith_cli.core_scaffold import add_entity_cmd, add_usecase_cmd


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


def test_add_usecase_creates_minimal_usecase_in_src_package(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(project_dir=project_dir, usecase_name="PlanShoppingList")

    assert generated == project_dir / "src" / "demo_service" / "application" / "use_cases" / "plan_shopping_list.py"
    assert generated.read_text(encoding="utf-8") == (
        "class PlanShoppingListUseCase:\n"
        "    async def execute(self) -> None:\n"
        '        raise NotImplementedError("Implement PlanShoppingListUseCase.execute")\n'
    )
    assert (project_dir / "src" / "demo_service" / "application" / "__init__.py").exists()
    assert (project_dir / "src" / "demo_service" / "application" / "use_cases" / "__init__.py").exists()
    assert not (project_dir / "src" / "demo_service" / "adapters").exists()


def test_add_usecase_does_not_duplicate_usecase_suffix(tmp_path: Path) -> None:
    project_dir = _src_project(tmp_path)

    generated = add_usecase_cmd(project_dir=project_dir, usecase_name="plan-shopping-list-use-case")

    assert generated.name == "plan_shopping_list.py"
    assert "class PlanShoppingListUseCase:" in generated.read_text(encoding="utf-8")
    assert "UseCaseUseCase" not in generated.read_text(encoding="utf-8")


def test_add_entity_supports_legacy_root_layout(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy-service"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text('[project]\nname = "legacy-service"\n', encoding="utf-8")

    generated = add_entity_cmd(project_dir=project_dir, entity_name="Recipe")

    assert generated == project_dir / "domain" / "models" / "recipe.py"
    assert (project_dir / "domain" / "__init__.py").exists()
    assert (project_dir / "domain" / "models" / "__init__.py").exists()
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
