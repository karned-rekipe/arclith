from pathlib import Path

import pytest

from arclith_cli.guide_models import (
    GuidePlanError,
    GuideStep,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.tui_models import ProjectDraft, render_plan


def _draft(
    tmp_path: Path,
    *,
    project_name: str = "catalog-service",
    intent: ProjectIntent = ProjectIntent.API_CRUD,
    entity: str = "Product",
    port: str = "8765",
) -> ProjectDraft:
    return ProjectDraft(
        parent_dir=str(tmp_path),
        project_name=project_name,
        intent=intent,
        entity=entity,
        usecase="CreateProduct",
        repository=RepositoryChoice.MEMORY,
        port=port,
        public_path="/v1/products",
    )


def test_project_draft_builds_api_plan(tmp_path: Path) -> None:
    plan = _draft(tmp_path).plan()

    assert plan.target_dir == tmp_path / "catalog-service"
    assert [step.command for step in plan.steps] == [
        "init",
        "add-entity",
        "add-adapter",
        "add-adapter",
        "expose-feature",
    ]
    assert plan.steps[3].args["params"] == {"port": "8765"}


def test_project_draft_keeps_minimal_choices_optional(tmp_path: Path) -> None:
    plan = _draft(
        tmp_path,
        intent=ProjectIntent.MINIMAL,
        entity="",
        port="not-used",
    ).plan()

    assert [step.command for step in plan.steps] == ["init"]


def test_project_draft_validates_runtime_port(tmp_path: Path) -> None:
    with pytest.raises(GuidePlanError, match="port doit être un entier"):
        _draft(tmp_path, port="eight-thousand").plan()


def test_render_plan_escapes_user_controlled_markup(tmp_path: Path) -> None:
    plan = ProjectPlan(
        target_dir=tmp_path / "catalog-service",
        intent=ProjectIntent.MINIMAL,
        steps=(
            GuideStep(
                title="Initialiser [service]",
                command="init",
                args={},
                argv=("init", "catalog-service"),
            ),
        ),
        creates_project=True,
    )

    rendered = render_plan(plan)

    assert "\\[service]" in rendered
    assert "1 étape" in rendered
