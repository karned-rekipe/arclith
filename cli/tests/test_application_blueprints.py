import asyncio
import importlib
import json
import re
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import pytest
import typer
import yaml
from typer.testing import CliRunner

from arclith_cli.application_blueprints import (
    application_blueprint_catalog_as_dict,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    add_application_blueprint_cmd,
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.feature_manifest import load_feature_manifest
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe

runner = CliRunner()
T = TypeVar("T")


def _project(tmp_path: Path, name: str = "blueprint-service") -> Path:
    project = init_project_cmd(project_name=name, directory=tmp_path)
    add_entity_cmd(project_dir=project, entity_name="Todo")
    return project


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    arguments: list[str],
    *,
    input_text: str | None = None,
):
    monkeypatch.chdir(project)
    return runner.invoke(app, arguments, input=input_text)


def test_crud_is_an_application_blueprint_not_an_adapter_capability() -> None:
    crud = get_application_blueprint("crud")

    assert crud.name == "crud"
    assert crud.operations == ("create", "get", "list", "update", "delete")
    assert application_blueprint_catalog_as_dict() == [
        {
            "name": "crud",
            "version": 1,
            "description": "Cycle de vie CRUD explicite pour une entité métier.",
            "operations": ["create", "get", "list", "update", "delete"],
        }
    ]


def test_crud_blueprint_generates_canonical_feature_layers(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )

    package = project / "src/blueprint_service"
    manifest_path = project / ".arclith/features/todo.yaml"
    manifest = load_feature_manifest(manifest_path)
    assert result.manifest_path == manifest_path
    assert manifest.feature == "todo"
    assert manifest.entity.name == "Todo"
    assert manifest.entity.module == "blueprint_service.domain.models.todo"
    assert manifest.blueprint.name == "crud"
    assert manifest.operations == ("create", "get", "list", "update", "delete")

    assert (package / "domain/errors/todo.py").is_file()
    for operation in manifest.operations:
        assert (package / f"domain/ports/inbound/{operation}_todo.py").is_file()
        assert (package / f"application/use_cases/{operation}_todo.py").is_file()
    assert (package / "infrastructure/containers/todo.py").is_file()
    assert (project / "tests/application/test_todo_crud.py").is_file()
    assert (project / "docs/blueprints/todo-crud.md").is_file()
    assert not (package / "adapters/inbound/fastapi").exists()
    assert not (package / "adapters/inbound/fastmcp").exists()


def test_crud_blueprint_replays_without_overwriting_developer_files(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    first = plan_application_blueprint(
        project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
    )
    apply_application_blueprint(first)
    create_use_case = (
        project / "src/blueprint_service/application/use_cases/create_todo.py"
    )
    create_use_case.write_text(
        create_use_case.read_text(encoding="utf-8") + "\n# developer rule\n",
        encoding="utf-8",
    )

    replay = plan_application_blueprint(
        project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
    )
    changed = apply_application_blueprint(replay)

    assert changed == ()
    assert create_use_case.read_text(encoding="utf-8").endswith("# developer rule\n")
    assert create_use_case in replay.preserved


def test_crud_blueprint_rejects_a_changed_canonical_manifest(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    manifest_path = project / ".arclith/features/todo.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["operations"] = ["create", "get"]
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="different canonical manifest"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
        )


@pytest.mark.parametrize(
    ("feature", "message"),
    [
        ("todo-item", "public Python identifier"),
        ("class", "public Python identifier"),
    ],
)
def test_feature_manifest_rejects_an_invalid_feature_identifier(
    tmp_path: Path,
    feature: str,
    message: str,
) -> None:
    manifest_path = tmp_path / "feature.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "feature": feature,
                "entity": {"name": "Todo", "module": "demo.domain.models.todo"},
                "blueprint": {"name": "crud", "version": 1},
                "operations": ["create"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_feature_manifest(manifest_path)


def test_crud_blueprint_dry_run_has_no_filesystem_or_recipe_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    result = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "crud", "--entity", "Todo", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (project / "arclith.recipe.yaml").exists()
    assert not (project / ".arclith/features/todo.yaml").exists()


def test_crud_blueprint_rejects_a_first_install_collision_without_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    conflict = project / "src/blueprint_service/application/use_cases/create_todo.py"
    conflict.write_text("# existing\n", encoding="utf-8")
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="already exists"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
        )

    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (project / ".arclith/features/todo.yaml").exists()


def test_crud_blueprint_executes_the_framework_crud_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "runtime-blueprint-service")
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    monkeypatch.syspath_prepend(str(project / "src"))
    container = importlib.import_module(
        "runtime_blueprint_service.infrastructure.containers.todo"
    )
    contracts = {
        operation: importlib.import_module(
            f"runtime_blueprint_service.domain.ports.inbound.{operation}_todo"
        )
        for operation in ("create", "get", "list", "update", "delete")
    }
    from arclith import Arclith

    use_cases = container.build_todo_use_cases(Arclith(project / "config"))
    created = _run(
        use_cases.create.execute(contracts["create"].CreateTodoCommand())
    ).item
    assert created.version == 1

    found = _run(
        use_cases.get.execute(contracts["get"].GetTodoQuery(uuid=created.uuid))
    )
    assert found.item == created

    page = _run(use_cases.list.execute(contracts["list"].ListTodoQuery()))
    assert page.items == [created]
    assert page.total == 1

    updated = _run(
        use_cases.update.execute(
            contracts["update"].UpdateTodoCommand(
                uuid=created.uuid,
                version=created.version,
            )
        )
    ).item
    assert updated.version == 2

    with pytest.raises(
        importlib.import_module(
            "runtime_blueprint_service.domain.errors.todo"
        ).TodoVersionConflictError
    ):
        _run(
            use_cases.update.execute(
                contracts["update"].UpdateTodoCommand(
                    uuid=created.uuid,
                    version=created.version,
                )
            )
        )

    deleted = _run(
        use_cases.delete.execute(
            contracts["delete"].DeleteTodoCommand(uuid=created.uuid)
        )
    )
    assert deleted.deleted is True
    with pytest.raises(
        importlib.import_module(
            "runtime_blueprint_service.domain.errors.todo"
        ).TodoNotFoundError
    ):
        _run(use_cases.get.execute(contracts["get"].GetTodoQuery(uuid=created.uuid)))

    for module in tuple(sys.modules):
        if module == "runtime_blueprint_service" or module.startswith(
            "runtime_blueprint_service."
        ):
            sys.modules.pop(module)


def _run(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_blueprints_command_and_add_blueprint_are_recipe_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)

    catalogue = _invoke(monkeypatch, project, ["blueprints", "--json"])
    assert catalogue.exit_code == 0, catalogue.output
    assert json.loads(catalogue.output)[0]["name"] == "crud"

    generated = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "crud", "--entity", "Todo", "--feature", "todo"],
    )
    assert generated.exit_code == 0, generated.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[-1].command == "add-blueprint"
    assert recipe.steps[-1].args["blueprint"] == "crud"
    assert recipe.steps[-1].args["entity"] == "Todo"
    assert recipe.steps[-1].args["feature"] == "todo"
    assert recipe.steps[-1].args["operations"] == [
        "create",
        "get",
        "list",
        "update",
        "delete",
    ]

    replay_target = tmp_path / "blueprint-replay"
    init_project_cmd(
        project_name="blueprint-service",
        target_path=replay_target,
    )
    add_entity_cmd(project_dir=replay_target, entity_name="Todo")
    replay_recipe(recipe, (recipe.steps[-1],), target_dir=replay_target, strict=True)
    assert (replay_target / ".arclith/features/todo.yaml").is_file()


def test_add_entity_crud_profile_is_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = runner.invoke(
        app,
        ["init", "profile-service", "--dir", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project = tmp_path / "profile-service"

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Todo", "--profile", "crud"],
    )
    assert result.exit_code == 0, result.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[-1].command == "add-entity"
    assert recipe.steps[-1].args["entity"] == "Todo"
    assert recipe.steps[-1].args["profile"] == "crud"
    assert recipe.steps[-1].args["blueprint_version"] == 1
    assert recipe.steps[-1].args["operations"] == [
        "create",
        "get",
        "list",
        "update",
        "delete",
    ]
    assert re.fullmatch(
        r"sha256:[a-f0-9]{64}", recipe.steps[-1].args["template_digest"]
    )

    replay_target = tmp_path / "profile-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    manifest = yaml.safe_load(
        (replay_target / ".arclith/features/todo.yaml").read_text(encoding="utf-8")
    )
    assert manifest["blueprint"]["name"] == "crud"
    assert manifest["operations"] == ["create", "get", "list", "update", "delete"]


def test_new_accepts_and_replays_the_crud_profile(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        [
            "new",
            "Todo",
            "new-crud-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "crud",
        ],
    )
    assert created.exit_code == 0, created.output
    project = tmp_path / "new-crud-service"
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[0].args["profile"] == "crud"
    assert recipe.steps[0].args["blueprint_version"] == 1
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", recipe.steps[0].args["template_digest"])
    assert (project / ".arclith/features/todo.yaml").is_file()

    replay_target = tmp_path / "new-crud-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    assert (replay_target / ".arclith/features/todo.yaml").is_file()


def test_add_entity_interactive_profile_choice_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="interactive-service", directory=tmp_path)

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity"],
        input_text="Todo\n2\n",
    )

    assert result.exit_code == 0, result.output
    assert "Profil applicatif initial" in result.output
    assert (project / ".arclith/features/todo.yaml").is_file()


def test_add_entity_direct_mode_keeps_the_minimal_profile_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="minimal-service", directory=tmp_path)

    result = _invoke(monkeypatch, project, ["add-entity", "Todo"])

    assert result.exit_code == 0, result.output
    assert not (project / ".arclith/features/todo.yaml").exists()
    assert load_recipe(project / "arclith.recipe.yaml").steps[-1].args == {
        "entity": "Todo",
        "profile": "minimal",
    }


def test_unknown_blueprint_and_profile_fail_without_partial_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="invalid-service", directory=tmp_path)

    with pytest.raises(ValueError, match="Unknown application blueprint"):
        get_application_blueprint("unknown")

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Todo", "--profile", "unknown"],
    )
    assert result.exit_code == 1
    assert not (project / "src/invalid_service/domain/models/todo.py").exists()
    assert not (project / ".arclith/features/todo.yaml").exists()

    new_result = runner.invoke(
        app,
        [
            "new",
            "Todo",
            "invalid-new-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "unknown",
        ],
    )
    assert new_result.exit_code == 1
    assert not (tmp_path / "invalid-new-service").exists()


def test_add_blueprint_requires_an_existing_entity(tmp_path: Path) -> None:
    project = init_project_cmd(project_name="empty-service", directory=tmp_path)

    with pytest.raises(typer.Exit):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )
