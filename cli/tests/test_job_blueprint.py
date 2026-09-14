import ast
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

from arclith_cli import blueprint_generation, job_blueprint
from arclith_cli.application_blueprints import (
    application_blueprint_digest,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.feature_manifest import FeatureManifest, load_feature_manifest
from arclith_cli.job_spec import JobSpec, load_job_spec
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe
from arclith_cli.recipe_models import save_recipe

runner = CliRunner()


def parameters(**updates):
    return {
        "request": "GenerateReportRequest",
        "result": "GenerateReportResult",
        "cancellable": True,
        "max_attempts": 2,
        "retention_days": 7,
        **updates,
    }


def project(tmp_path):
    result = runner.invoke(app, ["init", "report-service", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path / "report-service"


def write_spec(root, **updates):
    path = root / "job.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, **parameters(**updates)}), encoding="utf-8"
    )
    return path


def invoke(monkeypatch, root, args):
    monkeypatch.chdir(root)
    return runner.invoke(app, args)


def replay_file(path, target):
    recipe = load_recipe(path)
    return replay_recipe(recipe, recipe.steps, target_dir=target)


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def generate(monkeypatch, root, *, entity=False, **updates):
    spec = write_spec(root, **updates)
    target = ["--entity", "Document"] if entity else ["--no-entity"]
    result = invoke(
        monkeypatch,
        root,
        [
            "add-blueprint",
            "job",
            "--feature",
            "report_generation",
            *target,
            "--spec",
            str(spec),
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    return result


@pytest.mark.parametrize("color", [False, True])
def test_job_catalogue_and_help(color):
    output = runner.invoke(app, ["blueprints", "--json"])
    entry = next(item for item in json.loads(output.output) if item["name"] == "job")
    assert entry["operations"] == [
        "submit",
        "get_status",
        "cancel",
        "retry",
        "get_result",
    ]
    assert entry["parameterized"] is True
    help_result = runner.invoke(app, ["add-blueprint", "--help"], color=color)
    assert help_result.exit_code == 0, help_result.output
    assert "--no-entity" in unstyle(help_result.output)


@pytest.mark.parametrize("entity", [False, True])
@pytest.mark.parametrize("cancellable", [False, True])
def test_fresh_project_compiles_and_runs_generated_tests(
    tmp_path, monkeypatch, entity, cancellable
):
    root = project(tmp_path)
    if entity:
        add_entity_cmd(project_dir=root, entity_name="Document")
    before = tree(root)
    generate(monkeypatch, root, entity=entity, cancellable=cancellable)
    after = tree(root)
    assert all(
        after[path] == content
        for path, content in before.items()
        if path != "arclith.recipe.yaml"
    )
    manifest = load_feature_manifest(root / ".arclith/features/report_generation.yaml")
    assert manifest.version == 3
    assert (manifest.entity.name if manifest.entity else None) == (
        "Document" if entity else None
    )
    assert manifest.parameters == parameters(cancellable=cancellable)
    for path in root.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))
    for transport in ("fastapi", "fastmcp", "rabbitmq", "celery", "langgraph"):
        assert not any(transport in path for path in after.keys() - before.keys())
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 passed" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--no-entity", "--entity", "Document"],
        ["--no-entity"],
    ],
)
def test_invalid_target_has_no_side_effects(tmp_path, monkeypatch, args):
    root = project(tmp_path)
    spec = write_spec(root)
    before = tree(root)
    result = invoke(
        monkeypatch, root, ["add-blueprint", "job", *args, "--spec", str(spec)]
    )
    assert result.exit_code != 0
    assert tree(root) == before


@pytest.mark.parametrize("blueprint", ["crud", "append-only", "state-machine"])
def test_existing_blueprints_require_entity(tmp_path, monkeypatch, blueprint):
    root = project(tmp_path)
    before = tree(root)
    result = invoke(
        monkeypatch,
        root,
        ["add-blueprint", blueprint, "--no-entity", "--feature", "invalid"],
    )
    assert result.exit_code != 0
    assert tree(root) == before


def test_job_is_not_an_entity_profile(tmp_path, monkeypatch):
    root = project(tmp_path)
    before = tree(root)
    result = invoke(monkeypatch, root, ["add-entity", "Report", "--profile", "job"])
    assert result.exit_code != 0
    assert tree(root) == before


def test_dry_run_preservation_and_parameter_drift(tmp_path, monkeypatch):
    root = project(tmp_path)
    spec = write_spec(root)
    args = [
        "add-blueprint",
        "job",
        "--no-entity",
        "--feature",
        "report_generation",
        "--spec",
        str(spec),
    ]
    before = tree(root)
    result = invoke(monkeypatch, root, [*args, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert tree(root) == before
    generate(monkeypatch, root)
    handler = root / "src/report_service/application/jobs/report_generation.py"
    handler.write_text(
        handler.read_text() + "\n# user business code\n", encoding="utf-8"
    )
    before = tree(root)
    assert invoke(monkeypatch, root, args).exit_code == 0
    assert tree(root) == before
    write_spec(root, max_attempts=3)
    before = tree(root)
    result = invoke(monkeypatch, root, args)
    assert result.exit_code != 0 and "different canonical manifest" in " ".join(
        result.output.split()
    )
    assert tree(root) == before


@pytest.mark.parametrize(
    "collision",
    [
        "src/report_service/application/jobs/report_generation.py",
        "src/report_service/domain/ports/inbound/submit_report_generation.py",
        "docs/blueprints/report_generation-job.md",
    ],
)
def test_collision_is_atomic(tmp_path, monkeypatch, collision):
    root = project(tmp_path)
    spec = write_spec(root)
    path = root / collision
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("user content", encoding="utf-8")
    before = tree(root)
    result = invoke(
        monkeypatch,
        root,
        [
            "add-blueprint",
            "job",
            "--feature",
            "report_generation",
            "--no-entity",
            "--spec",
            str(spec),
        ],
    )
    assert result.exit_code != 0 and "already exists" in result.output
    assert tree(root) == before


def test_planned_write_race_and_failure_compensation(tmp_path, monkeypatch):
    root = project(tmp_path)
    plan = plan_application_blueprint(
        root,
        blueprint_name="job",
        entity_name=None,
        feature_name="report_generation",
        parameters=parameters(),
    )
    before = tree(root)
    original = blueprint_generation.write_new_text_file
    count = 0

    def fail_after_first(path, content):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("disk unavailable")
        return original(path, content)

    monkeypatch.setattr(blueprint_generation, "write_new_text_file", fail_after_first)
    with pytest.raises(OSError, match="disk unavailable"):
        apply_application_blueprint(plan)
    assert tree(root) == before

    path = next(iter(plan.files))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("concurrent edit", encoding="utf-8")
    before = tree(root)
    with pytest.raises(ValueError, match="changed after blueprint planning"):
        apply_application_blueprint(plan)
    assert tree(root) == before


@pytest.mark.parametrize("entity", [False, True])
def test_recipe_replay_is_portable_and_deterministic(tmp_path, monkeypatch, entity):
    root = project(tmp_path)
    if entity:
        result = invoke(monkeypatch, root, ["add-entity", "Document"])
        assert result.exit_code == 0
    generate(monkeypatch, root, entity=entity)
    recipe = load_recipe(root / "arclith.recipe.yaml")
    step = recipe.steps[-1]
    assert step.args["target_version"] == 1 and "spec" not in step.args
    (root / "job.yaml").unlink()
    replay = tmp_path / "replayed"
    replay_file(root / "arclith.recipe.yaml", replay)
    # The shared replay copies selected steps and derives envelope timestamps.
    assert load_recipe(replay / "arclith.recipe.yaml").steps == recipe.steps
    assert load_recipe(root / "arclith.recipe.yaml") == recipe
    for path, content in tree(root).items():
        if path == "arclith.recipe.yaml":
            continue
        assert (replay / path).read_bytes() == content, path


@pytest.mark.parametrize(
    "key,value",
    [
        ("target_version", True),
        ("target_version", 2),
        ("no_entity", "true"),
        ("entity", "Document"),
        ("feature", ""),
        ("parameters_digest", "sha256:" + "0" * 64),
        ("template_digest", "sha256:" + "0" * 64),
        ("operations", ["submit"]),
    ],
)
def test_bad_recipe_fails_before_creating_target(tmp_path, monkeypatch, key, value):
    root = project(tmp_path)
    generate(monkeypatch, root)
    path = root / "arclith.recipe.yaml"
    recipe = load_recipe(path)
    step = replace(recipe.steps[-1], args={**recipe.steps[-1].args, key: value})
    save_recipe(replace(recipe, steps=(*recipe.steps[:-1], step)), path)
    replay = tmp_path / "replay"
    with pytest.raises(ValueError):
        replay_file(path, replay)
    assert not replay.exists()


def test_legacy_state_machine_recipe_retains_exact_output(tmp_path):
    fixtures = Path(__file__).parent / "fixtures/job"
    target = tmp_path / "legacy"
    replay_file(fixtures / "legacy-state-machine.recipe.yaml", target)
    hashes = json.loads((fixtures / "legacy-state-machine.hashes.json").read_text())
    for path, digest in hashes.items():
        assert hashlib.sha256((target / path).read_bytes()).hexdigest() == digest, path
    assert (
        application_blueprint_digest(get_application_blueprint("state-machine"))
        == "sha256:41d495d9b5260515d545b4f88417014f0f1f0e4737cf81baf8dee77719a78767"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"version": True},
        {"version": 2},
        {"request": "invalid-name"},
        {"request": "BaseModel"},
        {"request": "GenerateReportResult"},
        {"result": "_Private"},
        {"result": "lowercase"},
        {"cancellable": "true"},
        {"max_attempts": True},
        {"max_attempts": 0},
        {"max_attempts": 101},
        {"retention_days": 0},
        {"retention_days": 3651},
        {"token": "not allowed"},
    ],
)
def test_spec_validation(updates):
    with pytest.raises(ValueError):
        JobSpec.from_dict({"version": 1, **parameters(), **updates})


def test_spec_digest_is_order_independent_and_requires_parameters(tmp_path):
    first = JobSpec.from_dict({"version": 1, **parameters()})
    second = JobSpec.from_dict(
        dict(reversed(list({"version": 1, **parameters()}.items())))
    )
    assert first.digest() == second.digest()
    for invalid in (None, {"version": 1}, {}):
        with pytest.raises(ValueError):
            JobSpec.from_parameters(invalid)
    with pytest.raises(ValueError, match="not found"):
        load_job_spec(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("[invalid", encoding="utf-8")
    with pytest.raises(ValueError, match="Unable to read"):
        load_job_spec(bad)


@pytest.mark.parametrize(
    "target",
    [{"kind": "other"}, {"kind": "standalone", "entity": {}}, {"kind": "entity"}],
)
def test_manifest_target_validation(tmp_path, monkeypatch, target):
    root = project(tmp_path)
    generate(monkeypatch, root)
    manifest = load_feature_manifest(root / ".arclith/features/report_generation.yaml")
    with pytest.raises(ValueError):
        FeatureManifest.from_dict({**manifest.to_dict(), "target": target})


def test_digest_tracks_standalone_renderer_branches(monkeypatch):
    blueprint = get_application_blueprint("job")
    before = application_blueprint_digest(blueprint)
    original = inspect.getsource
    monkeypatch.setattr(
        inspect,
        "getsource",
        lambda obj: (
            original(obj) + ("\n# standalone changed" if obj is job_blueprint else "")
        ),
    )
    assert application_blueprint_digest(blueprint) != before
