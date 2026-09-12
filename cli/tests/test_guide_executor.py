from pathlib import Path

import pytest

from arclith_cli.guide_executor import execute_project_plan, replay_recipe_atomically
from arclith_cli.guide_models import (
    GuideStep,
    NewProjectAnswers,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.recipe import RECIPE_FILENAME, load_recipe


def _crud_plan(tmp_path: Path) -> ProjectPlan:
    return plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name="catalog-service",
            intent=ProjectIntent.API_CRUD,
            entity="Product",
            usecase=None,
            repository=RepositoryChoice.MEMORY,
            transport_port=8090,
            public_path="/v1/products",
        )
    )


def _custom_plan(tmp_path: Path, intent: ProjectIntent) -> ProjectPlan:
    return plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name=f"{intent.value}-service",
            intent=intent,
            entity="Product",
            usecase="CreateProduct",
            repository=RepositoryChoice.MEMORY,
            transport_port=(8001 if intent == ProjectIntent.MCP else 8000),
            public_path=(
                "/v1/products"
                if intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}
                else None
            ),
        )
    )


def test_execute_crud_plan_creates_replayable_complete_project(tmp_path: Path) -> None:
    plan = _crud_plan(tmp_path)

    result = execute_project_plan(plan)

    assert result.root == tmp_path / "catalog-service"
    assert result.executed_commands == (
        "init",
        "add-entity",
        "add-adapter",
        "add-adapter",
        "expose-feature",
    )
    recipe = load_recipe(result.root / RECIPE_FILENAME)
    assert [step.command for step in recipe.steps] == list(result.executed_commands)
    assert recipe.steps[2].args["blueprint_version"] == "2"
    assert recipe.steps[-1].args["projection_version"] == 1
    assert (result.root / ".arclith" / "features" / "product.yaml").is_file()
    assert (
        result.root
        / "src"
        / "catalog_service"
        / "adapters"
        / "inbound"
        / "fastapi"
        / "routers"
        / "v1"
        / "product"
        / "routes"
        / "create_product.py"
    ).is_file()
    assert not list(tmp_path.glob(".catalog-service.arclith-*"))


def test_failed_new_project_plan_leaves_no_partial_target(
    tmp_path: Path,
) -> None:
    plan = _crud_plan(tmp_path)
    failing_step = GuideStep(
        title="Échec contrôlé",
        command="unsupported",
        args={},
        argv=("unsupported",),
    )
    broken = ProjectPlan(
        target_dir=plan.target_dir,
        intent=plan.intent,
        steps=(*plan.steps[:1], failing_step),
        creates_project=True,
    )

    with pytest.raises(ValueError, match="non supportée"):
        execute_project_plan(broken)

    assert not plan.target_dir.exists()
    assert not list(tmp_path.glob(".catalog-service.arclith-*"))


@pytest.mark.parametrize(
    ("intent", "adapter_manifest", "binding_manifest"),
    [
        (ProjectIntent.API_CUSTOM, "api-fastapi.yaml", "fastapi.json"),
        (ProjectIntent.MCP, "mcp-fastmcp.yaml", "fastmcp.json"),
        (ProjectIntent.AGENT, "agent-langgraph.yaml", "langgraph.json"),
        (
            ProjectIntent.WORKER,
            "command-bus-rabbitmq.yaml",
            "rabbitmq.json",
        ),
    ],
)
def test_execute_each_custom_intent_builds_transport_binding(
    tmp_path: Path,
    intent: ProjectIntent,
    adapter_manifest: str,
    binding_manifest: str,
) -> None:
    result = execute_project_plan(_custom_plan(tmp_path, intent))

    assert (result.root / ".arclith" / "blueprints" / adapter_manifest).is_file()
    assert (result.root / ".arclith" / "bindings" / binding_manifest).is_file()
    recipe = load_recipe(result.root / RECIPE_FILENAME)
    assert [step.command for step in recipe.steps] == [
        "init",
        "add-entity",
        "add-usecase",
        "add-adapter",
        "add-adapter",
        "expose-usecase",
    ]


def test_recipe_replay_is_atomic_and_reconstructs_the_project(tmp_path: Path) -> None:
    source = execute_project_plan(_crud_plan(tmp_path)).root
    recipe = load_recipe(source / RECIPE_FILENAME)
    target = tmp_path / "replayed-service"

    executed = replay_recipe_atomically(recipe, target_dir=target)

    assert executed == ("0001", "0002", "0003", "0004", "0005")
    assert (target / ".arclith" / "features" / "product.yaml").is_file()
    assert [step.command for step in load_recipe(target / RECIPE_FILENAME).steps] == [
        step.command for step in recipe.steps
    ]
    assert not list(tmp_path.glob(".replayed-service.arclith-replay-*"))


@pytest.mark.parametrize(
    "repository",
    [
        RepositoryChoice.MEMORY,
        RepositoryChoice.MONGODB,
        RepositoryChoice.POSTGRESQL,
    ],
)
def test_complete_crud_supports_each_guided_repository(
    tmp_path: Path,
    repository: RepositoryChoice,
) -> None:
    plan = plan_new_project(
        NewProjectAnswers(
            parent_dir=tmp_path,
            project_name=f"{repository.value}-catalog",
            intent=ProjectIntent.API_CRUD,
            entity="Product",
            usecase=None,
            repository=repository,
            transport_port=8000,
            public_path="/v1/products",
        )
    )

    result = execute_project_plan(plan)

    manifest = (
        result.root / ".arclith" / "blueprints" / f"repository-{repository.value}.yaml"
    )
    assert manifest.is_file()
    recipe = load_recipe(result.root / RECIPE_FILENAME)
    assert recipe.steps[2].args["adapter"] == repository.value
