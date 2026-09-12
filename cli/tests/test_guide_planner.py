from pathlib import Path

import pytest

from arclith_cli.guide_models import (
    GuidePlanError,
    NewProjectAnswers,
    ProjectIntent,
    RepositoryChoice,
)
from arclith_cli.guide_planner import (
    plan_add_adapter,
    plan_add_usecase,
    plan_new_project,
    shell_command,
)


def _answers(
    tmp_path: Path,
    intent: ProjectIntent,
    **overrides: object,
) -> NewProjectAnswers:
    values: dict[str, object] = {
        "parent_dir": tmp_path,
        "project_name": "catalog-service",
        "intent": intent,
        "entity": "Product",
        "usecase": "CreateProduct",
        "repository": RepositoryChoice.MEMORY,
        "transport_port": 8000,
        "public_path": "/v1/products",
    }
    values.update(overrides)
    return NewProjectAnswers(**values)  # type: ignore[arg-type]


def test_crud_api_plan_is_complete_and_has_no_side_effect(tmp_path: Path) -> None:
    plan = plan_new_project(_answers(tmp_path, ProjectIntent.API_CRUD))

    assert plan.target_dir == tmp_path / "catalog-service"
    assert plan.creates_project is True
    assert [step.command for step in plan.steps] == [
        "init",
        "add-entity",
        "add-adapter",
        "add-adapter",
        "expose-feature",
    ]
    assert plan.steps[1].args["profile"] == "crud"
    assert plan.steps[0].argv == (
        "init",
        "catalog-service",
        "--dir",
        str(tmp_path),
    )
    assert plan.steps[2].args["adapter"] == "memory"
    assert plan.steps[3].args["params"] == {"port": "8000"}
    assert plan.steps[4].args == {
        "feature": "product",
        "via": "fastapi",
        "http_path": "/v1/products",
    }
    assert not plan.target_dir.exists()


@pytest.mark.parametrize(
    ("intent", "transport", "binding"),
    [
        (ProjectIntent.API_CUSTOM, ("api", "fastapi"), "fastapi"),
        (ProjectIntent.MCP, ("mcp", "fastmcp"), "fastmcp"),
        (ProjectIntent.AGENT, ("agent", "langgraph"), "langgraph"),
        (ProjectIntent.WORKER, ("command-bus", "rabbitmq"), "rabbitmq"),
    ],
)
def test_custom_intent_plans_explicit_transport_and_binding(
    tmp_path: Path,
    intent: ProjectIntent,
    transport: tuple[str, str],
    binding: str,
) -> None:
    plan = plan_new_project(_answers(tmp_path, intent))

    assert [step.command for step in plan.steps] == [
        "init",
        "add-entity",
        "add-usecase",
        "add-adapter",
        "add-adapter",
        "expose-usecase",
    ]
    assert (
        plan.steps[4].args["capability"],
        plan.steps[4].args["adapter"],
    ) == transport
    assert plan.steps[5].args["via"] == binding
    if intent == ProjectIntent.WORKER:
        assert plan.steps[5].args["command_type"] == "product.create_product.v1"


def test_minimal_plan_can_stop_after_initialization(tmp_path: Path) -> None:
    plan = plan_new_project(
        _answers(
            tmp_path,
            ProjectIntent.MINIMAL,
            entity=None,
            usecase=None,
            repository=None,
            transport_port=None,
            public_path=None,
        )
    )

    assert [step.command for step in plan.steps] == ["init"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"entity": None}, "Une entité est requise"),
        ({"repository": None}, "repository explicite"),
        ({"transport_port": 70_000}, "port HTTP"),
        ({"public_path": "products"}, "sous /v1/"),
        ({"project_name": "bad name"}, "Nom de projet invalide"),
    ],
)
def test_invalid_answers_are_rejected_before_writes(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(GuidePlanError, match=message):
        plan_new_project(_answers(tmp_path, ProjectIntent.API_CRUD, **override))


def test_existing_target_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "catalog-service").mkdir()

    with pytest.raises(GuidePlanError, match="existe déjà"):
        plan_new_project(_answers(tmp_path, ProjectIntent.API_CRUD))


def test_equivalent_command_is_shell_quoted() -> None:
    step = plan_add_usecase(
        "Search",
        entity="Product",
        new_entity=None,
        no_entity=False,
    )

    assert shell_command(step) == "arclith-cli add-usecase Search --entity Product"


def test_equivalent_adapter_command_never_exposes_secrets() -> None:
    step = plan_add_adapter(
        "llm",
        "openai",
        params={"api_key": "super-secret"},
        profile=None,
        secret_params=frozenset({"api_key"}),
    )

    rendered = shell_command(step)
    assert "super-secret" not in rendered
    assert "'api_key=<redacted>'" in rendered
