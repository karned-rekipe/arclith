import ast
import builtins
import hashlib
import inspect
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from click import unstyle
from typer.testing import CliRunner

from arclith_cli import blueprint_generation, synchronization_blueprint
from arclith_cli.application_blueprints import (
    application_blueprint_digest,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.feature_manifest import load_feature_manifest
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe
from arclith_cli.recipe_models import save_recipe
from arclith_cli.synchronization_spec import (
    SynchronizationSpec,
    load_synchronization_spec,
)

runner = CliRunner()


def parameters(**updates):
    return {
        "direction": "pull",
        "modes": ["full", "incremental"],
        "external_key": "external_id",
        "page_size": 100,
        "conflict_policy": "source_wins",
        "missing_policy": "deactivate",
        "execution": "job",
        **updates,
    }


def invoke(args):
    return runner.invoke(app, args)


def project(tmp_path, monkeypatch):
    result = invoke(["init", "sync-service", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "sync-service"
    monkeypatch.chdir(root)
    assert invoke(["add-entity", "Customer"]).exit_code == 0
    return root


def spec_file(root, **updates):
    spec = root / "sync.yaml"
    spec.write_text(
        yaml.safe_dump({"version": 1, **parameters(**updates)}), encoding="utf-8"
    )
    return spec


def args(spec):
    return [
        "add-blueprint",
        "synchronization",
        "--entity",
        "Customer",
        "--feature",
        "customer_sync",
        "--spec",
        str(spec),
    ]


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def replay(path, target):
    recipe = load_recipe(path)
    return replay_recipe(recipe, recipe.steps, target_dir=target)


def test_catalogue_and_help():
    result = invoke(["blueprints", "--json"])
    entry = next(
        item for item in json.loads(result.output) if item["name"] == "synchronization"
    )
    assert entry["operations"] == [
        "start_sync",
        "get_sync_status",
        "cancel_sync",
        "get_sync_report",
    ]
    assert entry["parameterized"]
    assert "synchronization" in unstyle(invoke(["add-blueprint", "--help"]).output)


@pytest.mark.parametrize("policy", ["ignore", "deactivate"])
@pytest.mark.parametrize("modes", [["full"], ["incremental"], ["incremental", "full"]])
def test_fresh_project_compiles_runs_and_has_no_implicit_adapter(
    tmp_path, monkeypatch, policy, modes
):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root, missing_policy=policy, modes=modes)
    before_entity = (root / "src/sync_service/domain/models/customer.py").read_bytes()
    result = invoke(args(spec))
    assert result.exit_code == 0, (result.output, result.exception)
    for path in root.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))
    assert (
        root / "src/sync_service/domain/models/customer.py"
    ).read_bytes() == before_entity
    manifest = load_feature_manifest(root / ".arclith/features/customer_sync.yaml")
    assert manifest.version == 2 and manifest.entity.name == "Customer"
    assert manifest.parameters["modes"] == sorted(modes)
    assert manifest.parameters["max_full_items"] == 10000
    assert all(path.name == "__init__.py" for path in (root / "src/sync_service/adapters").rglob("*.py"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{len(modes) + 4} passed" in result.stdout


def test_dry_run_reapply_collision_and_parameter_drift_preserve_files(
    tmp_path, monkeypatch
):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root)
    before = tree(root)
    assert invoke([*args(spec), "--dry-run"]).exit_code == 0
    assert tree(root) == before
    assert invoke(args(spec)).exit_code == 0
    mapper = (
        root / "src/sync_service/application/synchronization/customer_sync_mapper.py"
    )
    mapper.write_text(
        mapper.read_text() + "\n# custom project mapping\n", encoding="utf-8"
    )
    before = tree(root)
    assert invoke(args(spec)).exit_code == 0
    assert tree(root) == before
    spec_file(root, page_size=30)
    before = tree(root)
    result = invoke(args(spec))
    assert result.exit_code != 0
    assert tree(root) == before


def test_portable_recipe_replays_without_original_spec(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root)
    assert invoke(args(spec)).exit_code == 0
    spec.unlink()
    target = tmp_path / "replay"
    replay(root / "arclith.recipe.yaml", target)
    for prefix in ("src", "tests", ".arclith/features", "docs/blueprints"):
        assert tree(root / prefix) == tree(target / prefix)


@pytest.mark.parametrize(
    "key,value",
    [
        ("template_digest", "sha256:" + "0" * 64),
        ("parameters_digest", "sha256:" + "0" * 64),
        ("operations", ["start_sync"]),
        ("blueprint_version", True),
        ("parameters", parameters(direction="push")),
    ],
)
def test_invalid_recipe_fails_before_writing_project(tmp_path, monkeypatch, key, value):
    root = project(tmp_path, monkeypatch)
    assert invoke(args(spec_file(root))).exit_code == 0
    path = root / "arclith.recipe.yaml"
    recipe = load_recipe(path)
    last = replace(recipe.steps[-1], args={**recipe.steps[-1].args, key: value})
    save_recipe(replace(recipe, steps=(*recipe.steps[:-1], last)), path)
    target = tmp_path / "invalid"
    with pytest.raises(ValueError):
        replay(path, target)
    assert not target.exists()


@pytest.mark.parametrize(
    "operation",
    [
        ["add-blueprint", "synchronization", "--no-entity", "--feature", "sync"],
        ["add-blueprint", "synchronization", "--entity", "Customer"],
        ["add-entity", "Wrong", "--profile", "synchronization"],
    ],
)
def test_target_and_spec_requirements_are_explicit(tmp_path, monkeypatch, operation):
    root = project(tmp_path, monkeypatch)
    before = tree(root)
    assert invoke(operation).exit_code != 0
    assert tree(root) == before


@pytest.mark.parametrize(
    "updates",
    [
        {"version": True},
        {"version": 2},
        {"page_size": 0},
        {"page_size": True},
        {"page_size": 1001},
        {"max_full_items": 100001},
        {"max_pages": 0},
        {"direction": "push"},
        {"modes": ["push"]},
        {"modes": []},
        {"modes": ["full", "full"]},
        {"conflict_policy": "target_wins"},
        {"missing_policy": "delete"},
        {"execution": "inline"},
        {"external_key": "a; import os"},
        {"external_key": "class"},
        {"external_key": "model_config"},
        {"external_key": "model_dump"},
        {"api_key": "must-not-persist"},
        {"source_version": "token=value"},
    ],
)
def test_invalid_spec_parameters(updates):
    with pytest.raises(ValueError):
        SynchronizationSpec.from_dict({"version": 1, **parameters(), **updates})


def test_spec_canonicalization_limits_and_utf8(tmp_path):
    a = SynchronizationSpec.from_dict(
        {"version": 1, **parameters(modes=["incremental", "full"])}
    )
    b = SynchronizationSpec.from_dict({"version": 1, **parameters()})
    assert a.digest() == b.digest()
    for raw in (None, {}, {"version": 1}):
        with pytest.raises(ValueError):
            SynchronizationSpec.from_parameters(raw)
    with pytest.raises(ValueError, match="not found"):
        load_synchronization_spec(tmp_path / "missing")
    path = tmp_path / "spec.yaml"
    for content in (b"[invalid", b"\xff"):
        path.write_bytes(content)
        with pytest.raises(ValueError, match="UTF-8 YAML"):
            load_synchronization_spec(path)
    path.write_bytes(b"a" * 65537)
    with pytest.raises(ValueError, match="64 KiB"):
        load_synchronization_spec(path)


def test_missing_runtime_is_reported_before_generation_or_replay(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root)
    assert invoke(args(spec)).exit_code == 0
    recipe = root / "arclith.recipe.yaml"
    original_import = builtins.__import__

    def incompatible(name, *args, **kwargs):
        if name == "arclith.application.services.synchronization":
            raise ImportError("missing synchronization/job runtime")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", incompatible)
    before = tree(root)
    result = invoke(args(spec))
    assert result.exit_code != 0 and "compatible framework and CLI" in result.output
    assert tree(root) == before
    target = tmp_path / "replay"
    with pytest.raises(ValueError, match="compatible framework and CLI"):
        replay(recipe, target)
    assert not target.exists()


def test_planned_collision_and_write_failure_are_atomic(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    plan = plan_application_blueprint(
        root,
        blueprint_name="synchronization",
        entity_name="Customer",
        feature_name="customer_sync",
        parameters=parameters(),
    )
    before = tree(root)
    original = blueprint_generation.write_new_text_file
    count = 0

    def fail_second(path, content):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated write failure")
        return original(path, content)

    monkeypatch.setattr(blueprint_generation, "write_new_text_file", fail_second)
    with pytest.raises(OSError):
        apply_application_blueprint(plan)
    assert tree(root) == before

    path = next(iter(plan.files))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("concurrent user edit", encoding="utf-8")
    before = tree(root)
    with pytest.raises(ValueError, match="changed after blueprint planning"):
        apply_application_blueprint(plan)
    assert tree(root) == before


def test_legacy_job_recipes_keep_exact_generated_files(tmp_path, monkeypatch):
    # Keep the captured package version stable; renderer compatibility is the
    # subject of this fixture, not the installed framework's release number.
    monkeypatch.setattr("arclith_cli.init_project._framework_version", lambda: "0.31.0")
    fixtures = Path(__file__).parent / "fixtures/synchronization"
    target = tmp_path / "legacy"
    replay(fixtures / "legacy-job.recipe.yaml", target)
    hashes = json.loads(
        (fixtures / "legacy-job.hashes.json").read_text(encoding="utf-8")
    )
    for path, digest in hashes.items():
        assert hashlib.sha256((target / path).read_bytes()).hexdigest() == digest, path


def test_source_contract_drift_changes_digest(monkeypatch):
    blueprint = get_application_blueprint("synchronization")
    baseline = application_blueprint_digest(blueprint)
    original = inspect.getsource

    def changed(module):
        return original(module) + (
            "\n# changed renderer" if module is synchronization_blueprint else ""
        )

    monkeypatch.setattr(inspect, "getsource", changed)
    assert application_blueprint_digest(blueprint) != baseline
