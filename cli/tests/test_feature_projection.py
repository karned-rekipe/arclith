"""Exercise explicit application-feature projections through a real FastAPI app."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arclith import Arclith
from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.blueprint_generation import add_application_blueprint_cmd
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.feature_projection import (
    apply_feature_projection,
    plan_feature_projection,
)
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe

runner = CliRunner()


def _project(tmp_path: Path, name: str = "feature-api") -> Path:
    project = init_project_cmd(project_name=name, directory=tmp_path)
    add_entity_cmd(project_dir=project, entity_name="Todo")
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    return project


def _install_fastapi(project: Path) -> None:
    add_adapter_cmd(
        project_dir=project,
        capability_name="api",
        adapter="fastapi",
        yes=True,
    )


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    arguments: list[str],
):
    monkeypatch.chdir(project)
    return runner.invoke(app, arguments)


def _snapshot(project: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def test_crud_feature_projection_generates_one_complete_rest_contract(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)

    plan = plan_feature_projection(
        project,
        feature_name="todo",
        via="fastapi",
        http_path="/v1/todos",
    )
    changed = apply_feature_projection(plan)

    assert changed
    assert [
        (item.method, item.http_path, item.status_code)
        for item in plan.binding_plan.options
    ] == [
        ("POST", "/v1/todos", 201),
        ("GET", "/v1/todos/{uuid}", 200),
        ("GET", "/v1/todos", 200),
        ("PATCH", "/v1/todos/{uuid}", 200),
        ("DELETE", "/v1/todos/{uuid}", 200),
    ]
    root = project / "src/feature_api/adapters/inbound/fastapi"
    for operation in ("create", "get", "list", "update", "delete"):
        assert (root / f"contracts/{operation}_todo.py").is_file()
        assert (root / f"routers/v1/todo/routes/{operation}_todo.py").is_file()

    manifest = json.loads(
        (project / ".arclith/bindings/fastapi.json").read_text(encoding="utf-8")
    )
    assert len(manifest["bindings"]) == 5
    containers = [entry["factory"]["container"] for entry in manifest["bindings"]]
    assert {item["builder"] for item in containers} == {"build_todo_use_cases"}
    assert {item["attribute"] for item in containers} == {
        "create",
        "get",
        "list",
        "update",
        "delete",
    }
    composition = (
        project / "src/feature_api/infrastructure/use_cases_generated.py"
    ).read_text(encoding="utf-8")
    assert composition.count("container_1 = build_container_1(arclith)") == 1
    assert "create_todo=container_1.create" in composition
    assert "delete_todo=container_1.delete" in composition


def test_default_feature_path_is_kebab_case_without_pluralization(
    tmp_path: Path,
) -> None:
    project = init_project_cmd(project_name="shopping-api", directory=tmp_path)
    add_entity_cmd(project_dir=project, entity_name="ShoppingItem")
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="ShoppingItem",
        feature_name="shopping_item",
        dry_run=False,
    )
    _install_fastapi(project)

    plan = plan_feature_projection(
        project,
        feature_name="shopping_item",
        via="fastapi",
        http_path=None,
    )

    assert {item.http_path for item in plan.binding_plan.options} == {
        "/v1/shopping-item",
        "/v1/shopping-item/{uuid}",
    }


def test_crud_feature_projection_executes_all_routes_and_error_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "runtime-feature-api")
    _install_fastapi(project)
    apply_feature_projection(
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )
    )
    monkeypatch.syspath_prepend(str(project / "src"))
    composition = importlib.import_module(
        "runtime_feature_api.infrastructure.use_cases_generated"
    )
    register = importlib.import_module(
        "runtime_feature_api.adapters.inbound.fastapi.register"
    )
    application = FastAPI()
    register.register_routes(
        application,
        composition.build_use_cases(Arclith(project / "config")),
    )
    client = TestClient(application)

    created = client.post("/v1/todos", json={})
    assert created.status_code == 201
    item = created.json()["item"]
    assert item["version"] == 1
    uuid = item["uuid"]

    found = client.get(f"/v1/todos/{uuid}")
    assert found.status_code == 200
    assert found.json()["item"] == item

    page = client.get("/v1/todos", params={"offset": 0, "limit": 10})
    assert page.status_code == 200
    assert page.json()["items"] == [item]
    assert page.json()["total"] == 1

    updated = client.patch(f"/v1/todos/{uuid}", json={"version": 1})
    assert updated.status_code == 200
    assert updated.json()["item"]["version"] == 2

    conflict = client.patch(f"/v1/todos/{uuid}", json={"version": 1})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "expected version 2, got 1"

    invalid = client.get("/v1/todos/not-a-uuid")
    assert invalid.status_code == 422

    deleted = client.delete(f"/v1/todos/{uuid}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    missing_after_delete = client.get(f"/v1/todos/{uuid}")
    repeated_delete = client.delete(f"/v1/todos/{uuid}")
    assert missing_after_delete.status_code == 404
    assert repeated_delete.status_code == 404

    openapi = application.openapi()["paths"]
    assert set(openapi) == {"/v1/todos", "/v1/todos/{uuid}"}
    assert openapi["/v1/todos"]["post"]["responses"]["201"]
    assert openapi["/v1/todos/{uuid}"]["get"]["responses"]["404"]
    assert openapi["/v1/todos/{uuid}"]["patch"]["responses"]["409"]

    for name in tuple(sys.modules):
        if name == "runtime_feature_api" or name.startswith("runtime_feature_api."):
            sys.modules.pop(name)


def test_feature_projection_requires_manifest_and_explicit_adapter(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    before = _snapshot(project)

    with pytest.raises(ValueError, match="Install the fastapi adapter"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path=None,
        )

    assert _snapshot(project) == before
    assert not (project / "src/feature_api/adapters/inbound/fastapi").exists()
    with pytest.raises(ValueError, match="Feature manifest not found"):
        plan_feature_projection(
            project,
            feature_name="unknown",
            via="fastapi",
            http_path=None,
        )


def test_feature_projection_rejects_manifest_drift_before_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    manifest_path = project / ".arclith/features/todo.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["operations"] = ["create", "get"]
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    before = _snapshot(project)

    with pytest.raises(ValueError, match="canonical blueprint"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )

    assert _snapshot(project) == before
    assert not (project / ".arclith/bindings/fastapi.json").exists()


def test_feature_projection_rejects_entity_manifest_drift_before_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    manifest_path = project / ".arclith/features/todo.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["entity"]["module"] = "feature_api.domain.models.other"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="entity module"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )

    assert not (project / ".arclith/bindings/fastapi.json").exists()


def test_feature_projection_rejects_container_drift_before_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    container = project / "src/feature_api/infrastructure/containers/todo.py"
    container.write_text(
        container.read_text(encoding="utf-8").replace(
            "def build_todo_use_cases", "def build_changed_use_cases"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="container"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )

    assert not (project / ".arclith/bindings/fastapi.json").exists()


@pytest.mark.parametrize(
    "signature",
    [
        "()",
        "(*, arclith: Arclith)",
        "(arclith: Arclith, required: str)",
    ],
)
def test_feature_projection_rejects_incompatible_builder_signatures_before_writes(
    tmp_path: Path,
    signature: str,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    container = project / "src/feature_api/infrastructure/containers/todo.py"
    container.write_text(
        container.read_text(encoding="utf-8").replace(
            "(arclith: Arclith) -> TodoUseCases",
            f"{signature} -> TodoUseCases",
        ),
        encoding="utf-8",
    )
    before = _snapshot(project)

    with pytest.raises(ValueError, match="container"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )

    assert _snapshot(project) == before
    assert not (project / ".arclith/bindings/fastapi.json").exists()


@pytest.mark.parametrize(
    ("via", "path", "message"),
    [
        ("fastmcp", None, "Supported feature projections"),
        ("fastapi", "/v1/todos/", "must not end"),
        ("fastapi", "/v1/todos/{uuid}", "must not contain path parameters"),
        ("fastapi", "/todos", "below the /v1"),
    ],
)
def test_feature_projection_rejects_unsupported_public_contracts(
    tmp_path: Path,
    via: str,
    path: str | None,
    message: str,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)

    with pytest.raises(ValueError, match=message):
        plan_feature_projection(
            project,
            feature_name="todo",
            via=via,
            http_path=path,
        )


def test_feature_projection_preflights_the_complete_batch_before_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    conflict = (
        project
        / "src/feature_api/adapters/inbound/fastapi/routers/v1/todo/routes/update_todo.py"
    )
    conflict.parent.mkdir(parents=True)
    conflict.write_text("# developer-owned collision\n", encoding="utf-8")
    before = _snapshot(project)

    with pytest.raises(ValueError, match="developer file already occupies"):
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )

    assert _snapshot(project) == before
    assert not (project / ".arclith/bindings/fastapi.json").exists()
    assert not (
        project / "src/feature_api/adapters/inbound/fastapi/contracts/create_todo.py"
    ).exists()


def test_feature_projection_dry_run_and_repeat_preserve_developer_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    before = _snapshot(project)
    command = [
        "expose-feature",
        "todo",
        "--via",
        "fastapi",
        "--path",
        "/v1/todos",
    ]

    dry_run = _invoke(monkeypatch, project, [*command, "--dry-run"])
    assert dry_run.exit_code == 0, dry_run.output
    assert "Dry-run" in dry_run.output
    assert _snapshot(project) == before

    first = _invoke(monkeypatch, project, command)
    assert first.exit_code == 0, first.output
    contract = (
        project / "src/feature_api/adapters/inbound/fastapi/contracts/create_todo.py"
    )
    contract.write_text(
        contract.read_text(encoding="utf-8") + "\n# developer customization\n",
        encoding="utf-8",
    )
    recipe_path = project / "arclith.recipe.yaml"
    recipe_before = recipe_path.read_text(encoding="utf-8")

    repeated = _invoke(monkeypatch, project, command)

    assert repeated.exit_code == 0, repeated.output
    assert contract.read_text(encoding="utf-8").endswith("# developer customization\n")
    assert recipe_path.read_text(encoding="utf-8") == recipe_before
    recipe = load_recipe(recipe_path)
    assert recipe.steps[-1].command == "expose-feature"
    assert recipe.steps[-1].args["http_path"] == "/v1/todos"
    assert recipe.steps[-1].args["operations"] == [
        "create",
        "get",
        "list",
        "update",
        "delete",
    ]


def test_feature_projection_recipe_recreates_the_public_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = runner.invoke(app, ["init", "recipe-feature-api", "--dir", str(tmp_path)])
    assert created.exit_code == 0, created.output
    project = tmp_path / "recipe-feature-api"
    assert (
        _invoke(
            monkeypatch,
            project,
            ["add-entity", "Todo", "--profile", "crud"],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            monkeypatch,
            project,
            ["add-adapter", "--capability", "api", "--adapter", "fastapi", "--yes"],
        ).exit_code
        == 0
    )
    exposed = _invoke(
        monkeypatch,
        project,
        [
            "expose-feature",
            "todo",
            "--via",
            "fastapi",
            "--path",
            "/v1/todos",
        ],
    )
    assert exposed.exit_code == 0, exposed.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert [step.command for step in recipe.steps] == [
        "init",
        "add-entity",
        "add-adapter",
        "expose-feature",
    ]

    replay_target = tmp_path / "recipe-feature-api-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)

    replay_manifest = json.loads(
        (replay_target / ".arclith/bindings/fastapi.json").read_text(encoding="utf-8")
    )
    assert len(replay_manifest["bindings"]) == 5
    assert {
        (entry["options"]["method"], entry["options"]["http_path"])
        for entry in replay_manifest["bindings"]
    } == {
        ("POST", "/v1/todos"),
        ("GET", "/v1/todos"),
        ("GET", "/v1/todos/{uuid}"),
        ("PATCH", "/v1/todos/{uuid}"),
        ("DELETE", "/v1/todos/{uuid}"),
    }


def test_feature_projection_upgrades_legacy_generated_file_headers(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _install_fastapi(project)
    registry = (
        project / "src/feature_api/adapters/inbound/fastapi/bindings_generated.py"
    )
    composition = project / "src/feature_api/infrastructure/use_cases_generated.py"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "# Generated by arclith-cli; edit the binding modules instead.",
            "# Generated by arclith-cli expose-usecase; edit the binding modules instead.",
            1,
        ),
        encoding="utf-8",
    )
    composition.write_text(
        composition.read_text(encoding="utf-8").replace(
            "# Generated by arclith-cli; do not edit manually.",
            "# Generated by arclith-cli expose-usecase; do not edit manually.",
            1,
        ),
        encoding="utf-8",
    )

    apply_feature_projection(
        plan_feature_projection(
            project,
            feature_name="todo",
            via="fastapi",
            http_path="/v1/todos",
        )
    )

    assert registry.read_text(encoding="utf-8").startswith(
        "# Generated by arclith-cli;"
    )
    assert composition.read_text(encoding="utf-8").startswith(
        "# Generated by arclith-cli;"
    )
