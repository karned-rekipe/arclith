import asyncio
import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from arclith.adapters.outbound.memory.append_only_store import (
    InMemoryAppendOnlyStore,
)
from arclith.domain.ports.outbound.append_only_store import AppendStatus
from arclith_cli.application_blueprints import get_application_blueprint
from arclith_cli.application_blueprint_recipe import replay_add_entity_step
from arclith_cli.blueprint_generation import (
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.feature_manifest import load_feature_manifest
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe

runner = CliRunner()


def _init_project(tmp_path: Path, name: str = "measurement-service") -> Path:
    return init_project_cmd(project_name=name, directory=tmp_path)


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    arguments: list[str],
):
    monkeypatch.chdir(project)
    return runner.invoke(app, arguments)


def _forget_package(package: str) -> None:
    for module in tuple(sys.modules):
        if module == package or module.startswith(f"{package}."):
            sys.modules.pop(module)


def test_append_only_is_discoverable_in_text_and_json_catalogues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _init_project(tmp_path)
    specification = get_application_blueprint("append-only")

    text_result = _invoke(monkeypatch, project, ["blueprints"])
    json_result = _invoke(monkeypatch, project, ["blueprints", "--json"])

    assert specification.operations == ("append",)
    assert specification.model_base == "immutable-record"
    assert text_result.exit_code == 0, text_result.output
    assert "append-only" in text_result.output
    catalog = json.loads(json_result.output)
    assert next(item for item in catalog if item["name"] == "append-only") == {
        "name": "append-only",
        "version": 1,
        "description": "Faits immuables avec append idempotent et conflit explicite.",
        "operations": ["append"],
    }


def test_append_only_profile_generates_an_immutable_transport_neutral_feature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _init_project(tmp_path)

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Measurement", "--profile", "append-only"],
    )

    assert result.exit_code == 0, result.output
    package = project / "src/measurement_service"
    model = (package / "domain/models/measurement.py").read_text(encoding="utf-8")
    manifest = load_feature_manifest(project / ".arclith/features/measurement.yaml")
    assert "class Measurement(ImmutableRecord):" in model
    assert "class Measurement(Entity):" not in model
    assert manifest.blueprint.name == "append-only"
    assert manifest.operations == ("append",)
    assert (package / "domain/ports/inbound/append_measurement.py").is_file()
    assert (package / "application/use_cases/append_measurement.py").is_file()
    assert (package / "infrastructure/containers/measurement.py").is_file()
    assert (project / "tests/application/test_measurement_append_only.py").is_file()
    assert (project / "docs/blueprints/measurement-append-only.md").is_file()
    assert not (package / "adapters/inbound/fastapi").exists()
    assert not (package / "adapters/inbound/fastmcp").exists()


def test_generated_append_only_feature_executes_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _init_project(tmp_path, "runtime-measurement-service")
    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Measurement", "--profile", "append-only"],
    )
    assert result.exit_code == 0, result.output
    monkeypatch.syspath_prepend(str(project / "src"))

    container = importlib.import_module(
        "runtime_measurement_service.infrastructure.containers.measurement"
    )
    contract = importlib.import_module(
        "runtime_measurement_service.domain.ports.inbound.append_measurement"
    )
    model = importlib.import_module(
        "runtime_measurement_service.domain.models.measurement"
    )
    store = InMemoryAppendOnlyStore()
    use_cases = container.build_measurement_use_cases(store)
    command = contract.AppendMeasurementCommand(
        record=model.Measurement(
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        idempotency_key="measurement-001",
    )

    first = asyncio.run(use_cases.append.execute(command))
    duplicate = asyncio.run(use_cases.append.execute(command))

    assert first.status is AppendStatus.APPENDED
    assert duplicate.status is AppendStatus.DUPLICATE
    assert len(store.inspect_records()) == 1
    _forget_package("runtime_measurement_service")


def test_append_only_dry_run_has_no_filesystem_or_recipe_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _init_project(tmp_path)
    add_entity_cmd(
        project_dir=project,
        entity_name="Measurement",
        model_base="immutable-record",
    )
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    result = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "append-only", "--entity", "Measurement", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (project / "arclith.recipe.yaml").exists()
    assert not (project / ".arclith/features/measurement.yaml").exists()


def test_append_only_rejects_a_mutable_entity_without_partial_writes(
    tmp_path: Path,
) -> None:
    project = _init_project(tmp_path)
    add_entity_cmd(project_dir=project, entity_name="Measurement")
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="requires a model based on ImmutableRecord"):
        plan_application_blueprint(
            project,
            blueprint_name="append-only",
            entity_name="Measurement",
            feature_name="measurement",
        )

    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before


def test_crud_rejects_an_immutable_record(tmp_path: Path) -> None:
    project = _init_project(tmp_path)
    add_entity_cmd(
        project_dir=project,
        entity_name="Measurement",
        model_base="immutable-record",
    )

    with pytest.raises(ValueError, match="requires a model based on Entity"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Measurement",
            feature_name="measurement",
        )


def test_append_only_first_install_collision_is_atomic(tmp_path: Path) -> None:
    project = _init_project(tmp_path)
    collision = (
        project / "src/measurement_service/application/use_cases/append_measurement.py"
    )
    collision.write_text("# developer-owned\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        replay_add_entity_step(
            project,
            {"entity": "Measurement", "profile": "append-only"},
        )

    assert not (
        project / "src/measurement_service/domain/models/measurement.py"
    ).exists()
    assert collision.read_text(encoding="utf-8") == "# developer-owned\n"
    assert not (project / ".arclith/features/measurement.yaml").exists()


def test_append_only_replay_preserves_developer_files_and_rejects_manifest_drift(
    tmp_path: Path,
) -> None:
    project = _init_project(tmp_path)
    add_entity_cmd(
        project_dir=project,
        entity_name="Measurement",
        model_base="immutable-record",
    )
    first = plan_application_blueprint(
        project,
        blueprint_name="append-only",
        entity_name="Measurement",
        feature_name="measurement_ingestion",
    )
    apply_application_blueprint(first)
    use_case = (
        project
        / "src/measurement_service/application/use_cases/append_measurement_ingestion.py"
    )
    use_case.write_text(
        use_case.read_text(encoding="utf-8") + "\n# developer rule\n",
        encoding="utf-8",
    )

    replay = plan_application_blueprint(
        project,
        blueprint_name="append-only",
        entity_name="Measurement",
        feature_name="measurement_ingestion",
    )
    assert apply_application_blueprint(replay) == ()
    assert use_case.read_text(encoding="utf-8").endswith("# developer rule\n")

    manifest_path = project / ".arclith/features/measurement_ingestion.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["operations"] = ["append", "delete"]
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="different canonical manifest"):
        plan_application_blueprint(
            project,
            blueprint_name="append-only",
            entity_name="Measurement",
            feature_name="measurement_ingestion",
        )


def test_new_append_only_profile_and_recipe_are_replayable(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "new",
            "Measurement",
            "append-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "append-only",
        ],
    )
    assert result.exit_code == 0, result.output
    project = tmp_path / "append-service"
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[0].args["profile"] == "append-only"
    assert recipe.steps[0].args["operations"] == ["append"]

    replay_target = tmp_path / "append-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    manifest = load_feature_manifest(
        replay_target / ".arclith/features/measurement.yaml"
    )
    model = (
        replay_target / "src/append_service/domain/models/measurement.py"
    ).read_text(encoding="utf-8")
    assert manifest.blueprint.name == "append-only"
    assert "class Measurement(ImmutableRecord):" in model


@pytest.mark.parametrize("collision_kind", ["file", "directory", "symlink"])
def test_profile_preflights_parent_and_target_collisions(
    tmp_path: Path,
    collision_kind: str,
) -> None:
    project = _init_project(tmp_path)
    docs = project / "docs/blueprints"
    docs.parent.mkdir(exist_ok=True)
    if collision_kind == "file":
        docs.write_text("developer content", encoding="utf-8")
    elif collision_kind == "directory":
        (docs / "measurement-append-only.md").mkdir(parents=True)
    else:
        destination = tmp_path / "external-docs"
        destination.mkdir()
        docs.symlink_to(destination, target_is_directory=True)
    before = set(project.rglob("*"))

    with pytest.raises(ValueError, match="Application blueprint"):
        replay_add_entity_step(
            project,
            {"entity": "Measurement", "profile": "append-only"},
        )

    assert set(project.rglob("*")) == before
    assert not (
        project / "src/measurement_service/domain/models/measurement.py"
    ).exists()


@pytest.mark.parametrize("business_fields", [False, True])
def test_fresh_append_only_project_compiles_and_runs_generated_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_fields: bool,
) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _init_project(tmp_path)
    if business_fields:
        model_path = add_entity_cmd(
            project_dir=project,
            entity_name="Measurement",
            model_base="immutable-record",
        )
        model_path.write_text(
            "from arclith import ImmutableRecord as Fact\n\n"
            "class Measurement(Fact):\n"
            "    sensor: str\n"
            "    value: float\n",
            encoding="utf-8",
        )
        arguments = [
            "add-blueprint",
            "append-only",
            "--entity",
            "Measurement",
            "--feature",
            "measurement_ingestion",
        ]
    else:
        arguments = ["add-entity", "Measurement", "--profile", "append-only"]
    result = _invoke(monkeypatch, project, arguments)
    assert result.exit_code == 0, result.output
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    for command in (
        [sys.executable, "-m", "compileall", "-q", "src"],
        [sys.executable, "-m", "pytest", "-p", "pytest_asyncio.plugin", "tests", "-q"],
    ):
        completed = subprocess.run(
            command,
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "declaration",
    [
        '    model_config = {"frozen": False}\n',
        '    recorded_at: str = "not-a-timestamp"\n',
        "    class Config:\n        frozen = False\n",
    ],
)
def test_append_only_rejects_changed_technical_contract(
    tmp_path: Path,
    declaration: str,
) -> None:
    project = _init_project(tmp_path)
    model = add_entity_cmd(
        project_dir=project,
        entity_name="Measurement",
        model_base="immutable-record",
    )
    model.write_text(
        "from arclith import ImmutableRecord\n\n"
        "class Measurement(ImmutableRecord):\n" + declaration,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must remain inherited"):
        plan_application_blueprint(
            project,
            blueprint_name="append-only",
            entity_name="Measurement",
            feature_name=None,
        )
    assert not (project / ".arclith/features/measurement.yaml").exists()
