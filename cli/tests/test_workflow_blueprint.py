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

from arclith_cli import blueprint_generation, workflow_blueprint
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
from arclith_cli.workflow_spec import WorkflowSpec, load_workflow_spec

runner = CliRunner()


def parameters(**updates):
    return {
        "context": "PublicationContext",
        "result": "PublicationResult",
        "steps": [
            {"name": "validate", "max_attempts": 2},
            {"name": "publish", "max_attempts": 1},
        ],
        **updates,
    }


def invoke(args):
    return runner.invoke(app, args)


def project(tmp_path, monkeypatch):
    output = invoke(["init", "workflow-service", "--dir", str(tmp_path)])
    assert output.exit_code == 0, output.output
    root = tmp_path / "workflow-service"
    monkeypatch.chdir(root)
    assert invoke(["add-entity", "Document"]).exit_code == 0
    return root


def spec_file(root, **updates):
    path = root / "workflow.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, **parameters(**updates)}), encoding="utf-8"
    )
    return path


def args(spec, *, entity=False):
    return [
        "add-blueprint",
        "workflow",
        "--feature",
        "publication",
        *(["--entity", "Document"] if entity else ["--no-entity"]),
        "--spec",
        str(spec),
    ]


def tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def replay(path, target):
    recipe = load_recipe(path)
    return replay_recipe(recipe, recipe.steps, target_dir=target)


def test_workflow_catalogue_and_help():
    entry = next(
        i
        for i in json.loads(invoke(["blueprints", "--json"]).output)
        if i["name"] == "workflow"
    )
    assert entry["operations"] == [
        "start",
        "get_status",
        "cancel",
        "resume",
        "get_result",
    ]
    assert entry["parameterized"]
    assert "workflow" in unstyle(invoke(["add-blueprint", "--help"]).output)


@pytest.mark.parametrize("entity", [False, True])
@pytest.mark.parametrize("attempts", [1, 2])
def test_fresh_project_types_extensions_and_runtime(
    tmp_path, monkeypatch, entity, attempts
):
    root = project(tmp_path, monkeypatch)
    original_entity = (
        root / "src/workflow_service/domain/models/document.py"
    ).read_bytes()
    spec = spec_file(
        root,
        steps=[
            {"name": "validate", "max_attempts": attempts},
            {"name": "publish", "max_attempts": 1},
        ],
    )
    output = invoke(args(spec, entity=entity))
    assert output.exit_code == 0, (output.output, output.exception)
    manifest = load_feature_manifest(root / ".arclith/features/publication.yaml")
    assert manifest.version == 3
    assert (manifest.entity is not None) is entity
    assert manifest.parameters["definition_version"] == 1
    assert (
        root / "src/workflow_service/domain/models/document.py"
    ).read_bytes() == original_entity
    for path in root.rglob("*.py"):
        ast.parse(path.read_text())
    assert all(
        p.name == "__init__.py"
        for p in (root / "src/workflow_service/adapters").rglob("*.py")
    )
    step = (
        root / "src/workflow_service/application/workflows/publication/steps/publish.py"
    )
    assert "raise NotImplementedError" in step.read_text()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    lint = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "E4,E7,E9,F,I,RUF059",
            "src",
            "tests/application",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr


@pytest.mark.parametrize("entity", [False, True])
def test_dry_run_replay_preserves_custom_steps_and_detects_drift(
    tmp_path, monkeypatch, entity
):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root)
    before = tree(root)
    assert invoke([*args(spec, entity=entity), "--dry-run"]).exit_code == 0
    assert tree(root) == before
    assert invoke(args(spec, entity=entity)).exit_code == 0
    custom = (
        root / "src/workflow_service/application/workflows/publication/steps/publish.py"
    )
    custom.write_text(custom.read_text() + "\n# project implementation\n")
    before = tree(root)
    assert invoke(args(spec, entity=entity)).exit_code == 0
    assert tree(root) == before
    recipe = root / "arclith.recipe.yaml"
    spec.unlink()
    target = tmp_path / "replayed"
    replay(recipe, target)
    assert (target / ".arclith/features/publication.yaml").read_bytes() == (
        root / ".arclith/features/publication.yaml"
    ).read_bytes()
    existing_recipe = load_recipe(recipe)
    replay_recipe(existing_recipe, existing_recipe.steps[-1:], target_dir=root)
    assert "# project implementation" in custom.read_text()
    spec_file(root, definition_version=2)
    before = tree(root)
    assert invoke(args(spec, entity=entity)).exit_code != 0
    assert tree(root) == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("target_version", True),
        ("no_entity", False),
        ("entity", "Document"),
        ("parameters", {}),
        ("operations", ["wrong"]),
        ("template_digest", "sha256:wrong"),
        ("parameters_digest", "sha256:wrong"),
    ],
)
def test_invalid_recipe_rejected_before_writes(tmp_path, monkeypatch, key, value):
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
    "updates",
    [
        {"version": True},
        {"version": 2},
        {"definition_version": 0},
        {"definition_version": True},
        {"steps": []},
        {"steps": [{"name": "same"}] * 2},
        {"steps": [{"name": "step", "max_attempts": 0}]},
        {"steps": [{"name": "step", "max_attempts": True}]},
        {"steps": [{"name": "step", "max_attempts": 101}]},
        {"steps": [{"name": "class"}]},
        {"steps": [{"name": "a; import os"}]},
        {"steps": [{"name": "step", "code": "print()"}]},
        {"context": "invalid.name"},
        {"context": "PublicationResult"},
        {"context": "BaseModel"},
        {"api_key": "not-permitted"},
    ],
)
def test_invalid_spec(updates):
    with pytest.raises(ValueError):
        WorkflowSpec.from_dict({"version": 1, **parameters(), **updates})


def test_canonical_order_defaults_and_file_bounds(tmp_path):
    one = WorkflowSpec.from_dict(
        {"version": 1, **parameters(steps=[{"name": "first"}, {"name": "second"}])}
    )
    explicit = WorkflowSpec.from_parameters(one.to_parameters())
    assert one == explicit and one.digest() == explicit.digest()
    reverse = WorkflowSpec.from_parameters(
        {**one.to_parameters(), "steps": list(reversed(one.to_parameters()["steps"]))}
    )
    assert reverse.digest() != one.digest()
    for raw in (None, {}, {"version": 1}):
        with pytest.raises(ValueError):
            WorkflowSpec.from_parameters(raw)
    with pytest.raises(ValueError, match="not found"):
        load_workflow_spec(tmp_path / "missing")
    path = tmp_path / "bad.yaml"
    for value in (b"[invalid", b"\xff", b"a" * 65537):
        path.write_bytes(value)
        with pytest.raises(ValueError):
            load_workflow_spec(path)


@pytest.mark.parametrize(
    "operation",
    [
        ["add-blueprint", "workflow", "--no-entity"],
        ["add-blueprint", "workflow", "--entity", "Document"],
        ["add-blueprint", "workflow", "--feature", "publication"],
        ["add-entity", "Wrong", "--profile", "workflow"],
    ],
)
def test_target_spec_requirements(tmp_path, monkeypatch, operation):
    root = project(tmp_path, monkeypatch)
    before = tree(root)
    assert invoke(operation).exit_code != 0
    assert tree(root) == before


def test_missing_runtime_before_generation_and_replay(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    spec = spec_file(root)
    assert invoke(args(spec)).exit_code == 0
    original = builtins.__import__

    def incompatible(name, *args, **kwargs):
        if name == "arclith.application.services.workflow_runner":
            raise ImportError("missing runtime")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", incompatible)
    before = tree(root)
    output = invoke(args(spec))
    assert (
        output.exit_code != 0
        and "compatible Arclith framework and CLI" in output.output
    )
    assert tree(root) == before
    with pytest.raises(ValueError, match="compatible Arclith"):
        replay(root / "arclith.recipe.yaml", tmp_path / "replayed")
    assert not (tmp_path / "replayed").exists()


def test_write_rollback_and_concurrent_collision(tmp_path, monkeypatch):
    root = project(tmp_path, monkeypatch)
    plan = plan_application_blueprint(
        root,
        blueprint_name="workflow",
        entity_name=None,
        feature_name="publication",
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
    path.write_text("user edit")
    before = tree(root)
    with pytest.raises(ValueError, match="changed after blueprint planning"):
        apply_application_blueprint(plan)
    assert tree(root) == before


def test_legacy_blueprint_digests_and_exact_sync_replay(tmp_path, monkeypatch):
    # The historical fixture includes pyproject.toml from framework 0.31.0.
    monkeypatch.setattr("arclith_cli.init_project._framework_version", lambda: "0.31.0")
    fixtures = Path(__file__).parent / "fixtures/workflow"
    for name, digest in json.loads(
        (fixtures / "legacy-digests.json").read_text()
    ).items():
        assert application_blueprint_digest(get_application_blueprint(name)) == digest
    target = tmp_path / "legacy"
    replay(fixtures / "legacy-sync.recipe.yaml", target)
    for path, digest in json.loads(
        (fixtures / "legacy-sync.hashes.json").read_text()
    ).items():
        assert hashlib.sha256((target / path).read_bytes()).hexdigest() == digest, path


def test_source_changes_still_drift(monkeypatch):
    blueprint = get_application_blueprint("workflow")
    baseline = application_blueprint_digest(blueprint)
    original = inspect.getsource

    def changed(module):
        return original(module) + (
            "\n# changed renderer" if module is workflow_blueprint else ""
        )

    monkeypatch.setattr(inspect, "getsource", changed)
    assert application_blueprint_digest(blueprint) != baseline
