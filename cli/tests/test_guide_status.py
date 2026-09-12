from pathlib import Path

from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    NewProjectAnswers,
    ProjectIntent,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.guide_status import find_project_root, inspect_project


def _project(tmp_path: Path) -> Path:
    plan = plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name="catalog-service",
            intent=ProjectIntent.API_CRUD,
            entity="Product",
            usecase=None,
            repository=RepositoryChoice.MEMORY,
            transport_port=8000,
            public_path="/v1/products",
        )
    )
    return execute_project_plan(plan).root


def test_inspect_project_reports_current_generated_state(tmp_path: Path) -> None:
    project = _project(tmp_path)

    overview = inspect_project(project)

    assert overview.name == "catalog-service"
    assert overview.package == "catalog_service"
    assert overview.entities == ("Product",)
    assert overview.usecases == (
        "create_product",
        "delete_product",
        "get_product",
        "list_product",
        "update_product",
    )
    assert [(item.name, item.entity, item.blueprint) for item in overview.features] == [
        ("product", "Product", "crud")
    ]
    assert overview.adapters == ("api/fastapi", "repository/memory")
    assert overview.issues == ()
    assert find_project_root(project / "src" / "catalog_service") == project


def test_inspect_project_surfaces_invalid_metadata(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / ".arclith" / "features" / "broken.yaml").write_text(
        "not: a-feature\n",
        encoding="utf-8",
    )
    (project / ".arclith" / "blueprints" / "broken.yaml").write_text(
        "capability: api\n",
        encoding="utf-8",
    )

    overview = inspect_project(project)

    assert len(overview.issues) == 2
    assert overview.issues[0].startswith("Feature invalide (broken.yaml)")
    assert overview.issues[1].startswith("Adapter invalide (broken.yaml)")


def test_find_project_root_returns_none_outside_project(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) is None


def test_status_keeps_support_for_legacy_root_layout(tmp_path: Path) -> None:
    (tmp_path / "domain" / "models").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "legacy-service"\n',
        encoding="utf-8",
    )

    overview = inspect_project(tmp_path)

    assert overview.name == "legacy-service"
    assert overview.package == tmp_path.name
    assert overview.issues == ("Recette absente : arclith.recipe.yaml",)
