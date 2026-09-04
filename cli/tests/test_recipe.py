from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from arclith_cli.main import app
from arclith_cli.recipe import (
    RECIPE_FILENAME,
    REDACTED,
    RecipeError,
    load_recipe,
    record_successful_step,
    snapshot_project_files,
)

runner = CliRunner()


def _init_project(tmp_path: Path, name: str = "demo-service") -> Path:
    result = runner.invoke(app, ["init", name, "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path / name


def _invoke_in_project(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    arguments: list[str],
):
    monkeypatch.chdir(project_dir)
    return runner.invoke(app, arguments)


def test_init_creates_versioned_recipe_with_relative_files(tmp_path: Path) -> None:
    project_dir = _init_project(tmp_path)

    recipe = load_recipe(project_dir / RECIPE_FILENAME)

    assert recipe.version == 1
    assert recipe.project.name == "demo-service"
    assert recipe.project.package == "demo_service"
    assert [step.command for step in recipe.steps] == ["init"]
    assert recipe.steps[0].args == {
        "project_name": "demo-service",
        "directory": ".",
    }
    assert recipe.steps[0].result.generated_files
    assert all(
        not Path(change.path).is_absolute()
        for change in recipe.steps[0].result.generated_files
    )
    assert all(
        RECIPE_FILENAME != change.path
        for change in recipe.steps[0].result.generated_files
    )


def test_new_creates_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_new_project_cmd(**kwargs: object) -> Path:
        target = Path(str(kwargs["directory"])) / str(kwargs["project_name"])
        package = str(kwargs["project_name"]).replace("-", "_")
        (target / "src" / package).mkdir(parents=True)
        (target / "src" / package / "__init__.py").write_text("", encoding="utf-8")
        (target / "pyproject.toml").write_text(
            f'[project]\nname = "{kwargs["project_name"]}"\n',
            encoding="utf-8",
        )
        return target

    monkeypatch.setattr("arclith_cli.main._new_project_cmd", fake_new_project_cmd)

    result = runner.invoke(
        app,
        [
            "new",
            "Widget",
            "template-service",
            "--dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    recipe = load_recipe(tmp_path / "template-service" / RECIPE_FILENAME)
    assert [step.command for step in recipe.steps] == ["new"]
    assert recipe.steps[0].args == {
        "entity": "Widget",
        "project_name": "template-service",
        "directory": ".",
        "port": 8000,
        "repo_ref": "main",
    }


def test_core_commands_append_only_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)

    for arguments in (
        ["add-entity", "ShoppingItem"],
        ["add-usecase", "PlanShoppingList", "--entity", "ShoppingItem"],
        ["add-intent-interpreter", "ShoppingIntent"],
    ):
        result = _invoke_in_project(monkeypatch, project_dir, arguments)
        assert result.exit_code == 0, result.output

    recipe = load_recipe(project_dir / RECIPE_FILENAME)
    assert [step.command for step in recipe.steps] == [
        "init",
        "add-entity",
        "add-usecase",
        "add-intent-interpreter",
    ]
    assert [step.id for step in recipe.steps] == ["0001", "0002", "0003", "0004"]

    failed = _invoke_in_project(
        monkeypatch,
        project_dir,
        ["add-entity", "ShoppingItem"],
    )
    assert failed.exit_code == 1
    assert len(load_recipe(project_dir / RECIPE_FILENAME).steps) == 4


def test_add_adapter_records_resolved_params_and_generated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)
    assert (
        _invoke_in_project(monkeypatch, project_dir, ["add-entity", "Widget"]).exit_code
        == 0
    )

    result = _invoke_in_project(
        monkeypatch,
        project_dir,
        [
            "add-adapter",
            "--capability",
            "repository",
            "--adapter",
            "memory",
            "--entity",
            "Widget",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    step = load_recipe(project_dir / RECIPE_FILENAME).steps[-1]
    assert step.command == "add-adapter"
    assert step.args == {
        "capability": "repository",
        "adapter": "memory",
        "entities": ["Widget"],
        "activate": True,
        "profile": None,
        "params": {},
    }
    changed_paths = {change.path for change in step.result.generated_files}
    assert (
        "src/demo_service/adapters/outbound/memory/repositories/widget_repository.py"
        in changed_paths
    )
    assert "config/adapters/adapters.yaml" not in changed_paths


def test_interactive_and_direct_adapter_inputs_record_the_same_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_project = _init_project(tmp_path, "direct-service")
    interactive_project = _init_project(tmp_path, "interactive-service")
    for project_dir in (direct_project, interactive_project):
        assert (
            _invoke_in_project(
                monkeypatch, project_dir, ["add-entity", "Widget"]
            ).exit_code
            == 0
        )

    direct = _invoke_in_project(
        monkeypatch,
        direct_project,
        ["add-adapter", "--adapter", "memory", "--entity", "Widget", "--yes"],
    )
    assert direct.exit_code == 0, direct.output
    monkeypatch.chdir(interactive_project)
    interactive = runner.invoke(
        app,
        ["add-adapter", "--adapter", "memory"],
        input="\n\n",
    )
    assert interactive.exit_code == 0, interactive.output

    direct_args = load_recipe(direct_project / RECIPE_FILENAME).steps[-1].args
    interactive_args = load_recipe(interactive_project / RECIPE_FILENAME).steps[-1].args
    assert direct_args == interactive_args


def test_add_adapter_redacts_catalog_and_uri_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)
    secret_uri = "redis://recipe-user:never-write-me@redis:6379/0"

    result = _invoke_in_project(
        monkeypatch,
        project_dir,
        [
            "add-adapter",
            "--capability",
            "cache",
            "--adapter",
            "redis",
            "--param",
            f"redis_url={secret_uri}",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    recipe_path = project_dir / RECIPE_FILENAME
    raw = recipe_path.read_text(encoding="utf-8")
    step = load_recipe(recipe_path).steps[-1]
    assert "never-write-me" not in raw
    assert step.args["params"]["redis_url"] == REDACTED
    assert {
        (secret.field_path, secret.source, secret.key) for secret in step.secrets
    } == {
        ("args.params.redis_url", "env", "REDIS_URL"),
        ("cache.redis_url", "env", "REDIS_URL"),
    }


def test_history_displays_ordered_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)
    assert (
        _invoke_in_project(monkeypatch, project_dir, ["add-entity", "Widget"]).exit_code
        == 0
    )

    result = _invoke_in_project(monkeypatch, project_dir, ["history"])

    assert result.exit_code == 0, result.output
    assert "0001" in result.output
    assert "init" in result.output
    assert "0002" in result.output
    assert "add-entity" in result.output
    assert "Widget" in result.output


def test_replay_dry_run_does_not_touch_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)
    assert (
        _invoke_in_project(monkeypatch, project_dir, ["add-entity", "Widget"]).exit_code
        == 0
    )
    target = tmp_path / "dry-run-target"

    result = runner.invoke(
        app,
        [
            "replay",
            str(project_dir / RECIPE_FILENAME),
            "--dir",
            str(target),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dry-run" in result.output
    assert "add-entity" in result.output
    assert not target.exists()


def test_snapshot_detects_symlink_target_changes(tmp_path: Path) -> None:
    link = tmp_path / "current-config"
    link.symlink_to("config-v1.yaml")
    before = snapshot_project_files(tmp_path)

    link.unlink()
    link.symlink_to("config-v2.yaml")
    after = snapshot_project_files(tmp_path)

    assert before[link.name] != after[link.name]


def test_snapshot_reports_unreadable_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = tmp_path / "current-config"
    link.symlink_to("config-v1.yaml")

    def fail_readlink(path: Path) -> str:
        raise OSError("readlink denied")

    monkeypatch.setattr("arclith_cli.recipe.os.readlink", fail_readlink)

    with pytest.raises(RecipeError, match="Unable to inspect generated symlink"):
        snapshot_project_files(tmp_path)


def test_non_strict_dry_run_marks_unsupported_steps_as_ignored(
    tmp_path: Path,
) -> None:
    project_dir = _init_project(tmp_path)
    recipe_path = project_dir / RECIPE_FILENAME
    raw = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    unknown = dict(raw["steps"][0])
    unknown.update(
        {
            "id": "0002",
            "command": "add-blueprint",
            "args": {"token": REDACTED},
            "secrets": [
                {
                    "field_path": "args.token",
                    "source": "env",
                    "key": "IGNORED_BLUEPRINT_TOKEN",
                    "value": REDACTED,
                }
            ],
        }
    )
    raw["steps"].append(unknown)
    recipe_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    target = tmp_path / "non-strict-target"

    result = runner.invoke(
        app,
        [
            "replay",
            str(recipe_path),
            "--dir",
            str(target),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "add-blueprint" in result.output
    assert "ignorer (non supportée)" in result.output
    assert "1 étape(s) à exécuter, 1 ignorée(s)" in result.output
    assert "IGNORED_BLUEPRINT_TOKEN" not in result.output
    assert not target.exists()


def test_strict_dry_run_rejects_unknown_command_without_writing(
    tmp_path: Path,
) -> None:
    project_dir = _init_project(tmp_path)
    recipe_path = project_dir / RECIPE_FILENAME
    raw = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    unknown = dict(raw["steps"][0])
    unknown.update({"id": "0002", "command": "add-blueprint"})
    raw["steps"].append(unknown)
    recipe_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    target = tmp_path / "strict-target"

    result = runner.invoke(
        app,
        [
            "replay",
            str(recipe_path),
            "--dir",
            str(target),
            "--dry-run",
            "--strict",
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported recipe commands" in result.output
    assert not target.exists()


def test_replay_preflights_missing_secrets_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path)
    result = _invoke_in_project(
        monkeypatch,
        project_dir,
        [
            "add-adapter",
            "--capability",
            "cache",
            "--adapter",
            "redis",
            "--param",
            "redis_url=redis://user:password@redis:6379/0",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    monkeypatch.delenv("REDIS_URL", raising=False)
    target = tmp_path / "missing-secret-target"

    replayed = runner.invoke(
        app,
        [
            "replay",
            str(project_dir / RECIPE_FILENAME),
            "--dir",
            str(target),
        ],
    )

    assert replayed.exit_code == 1
    assert "requires environment variable REDIS_URL" in replayed.output
    assert not target.exists()


def test_replay_rebuilds_minimal_project_without_duplicate_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _init_project(tmp_path, "source-service")
    for arguments in (
        ["add-entity", "Widget"],
        ["add-usecase", "CreateWidget", "--entity", "Widget"],
        [
            "add-adapter",
            "--capability",
            "repository",
            "--adapter",
            "memory",
            "--entity",
            "Widget",
            "--yes",
        ],
    ):
        result = _invoke_in_project(monkeypatch, project_dir, arguments)
        assert result.exit_code == 0, result.output

    recipe_path = project_dir / RECIPE_FILENAME
    target = tmp_path / "rebuilt-project"
    result = runner.invoke(
        app,
        ["replay", str(recipe_path), "--dir", str(target)],
    )

    assert result.exit_code == 0, result.output
    package_root = target / "src" / "source_service"
    assert (package_root / "domain" / "models" / "widget.py").is_file()
    assert (package_root / "application" / "use_cases" / "create_widget.py").is_file()
    assert (
        package_root
        / "adapters"
        / "outbound"
        / "memory"
        / "repositories"
        / "widget_repository.py"
    ).is_file()
    source = load_recipe(recipe_path)
    replayed = load_recipe(target / RECIPE_FILENAME)
    assert [step.id for step in replayed.steps] == [step.id for step in source.steps]
    assert [step.command for step in replayed.steps] == [
        step.command for step in source.steps
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty"),
        (
            yaml.safe_dump(
                {
                    "version": 999,
                    "project": {"name": "demo", "package": "demo"},
                    "created_at": "2026-09-01T00:00:00+00:00",
                    "updated_at": "2026-09-01T00:00:00+00:00",
                    "steps": [],
                }
            ),
            "Unsupported recipe schema version",
        ),
    ],
)
def test_load_recipe_rejects_empty_or_unsupported_schema(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    recipe_path = tmp_path / RECIPE_FILENAME
    recipe_path.write_text(content, encoding="utf-8")

    with pytest.raises(RecipeError, match=message):
        load_recipe(recipe_path)


def test_history_reports_missing_recipe(tmp_path: Path) -> None:
    missing = tmp_path / RECIPE_FILENAME

    result = runner.invoke(app, ["history", "--recipe", str(missing)])

    assert result.exit_code == 1
    assert "Recipe file not found" in result.output


def test_recipe_identity_falls_back_when_pyproject_is_malformed(tmp_path: Path) -> None:
    project_dir = tmp_path / "fallback-service"
    (project_dir / "src" / "fallback_service").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[invalid", encoding="utf-8")

    record_successful_step(
        project_dir,
        command="add-entity",
        args={"entity": "Widget"},
        before={},
    )

    recipe = load_recipe(project_dir / RECIPE_FILENAME)
    assert recipe.project.name == "fallback-service"
    assert recipe.project.package == "fallback_service"
