from pathlib import Path

import pytest
import typer

from arclith_cli.add_adapter import add_adapter_cmd


def _write_model(project_dir: Path, package_name: str, class_name: str, file_name: str) -> None:
    model_dir = project_dir / "src" / package_name / "domain" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / f"{file_name}.py").write_text(
        "from arclith.domain.models.entity import Entity\n\n"
        f"class {class_name}(Entity):\n"
        "    pass\n",
        encoding="utf-8",
    )


def _minimal_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "demo-service"
    package_name = "demo_service"
    _write_model(project_dir, package_name, "Widget", "widget")
    (project_dir / "src" / package_name / "adapters" / "outbound").mkdir(parents=True)
    (project_dir / "src" / package_name / "infrastructure" / "containers").mkdir(parents=True)
    config_dir = project_dir / "config" / "adapters"
    config_dir.mkdir(parents=True)
    (config_dir / "adapters.yaml").write_text("logger: console\nrepository: memory\n", encoding="utf-8")
    return project_dir


def test_add_duckdb_adapter_non_interactive(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="duckdb",
        duckdb_path="data/widgets.parquet",
        yes=True,
    )

    package_root = project_dir / "src" / "demo_service"
    assert (package_root / "adapters" / "outbound" / "duckdb" / "repositories" / "widget_repository.py").exists()
    assert (package_root / "adapters" / "outbound" / "duckdb" / "repository.py").exists()
    assert 'register("duckdb", _build_duckdb)' in (
        package_root / "infrastructure" / "containers" / "widget_container.py"
    ).read_text(encoding="utf-8")
    assert "repository: duckdb" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "path: data/widgets.parquet" in (
        project_dir / "config" / "adapters" / "outbound" / "duckdb.yaml"
    ).read_text(encoding="utf-8")


def test_add_mongodb_adapter_uses_non_interactive_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mongodb",
        entity_names=["Widget"],
        activate=False,
        db_name="demo_shared",
        multitenant=True,
        yes=True,
    )

    mongodb_config = (project_dir / "config" / "adapters" / "outbound" / "mongodb.yaml").read_text(
        encoding="utf-8"
    )
    assert "multitenant: true" in mongodb_config
    assert "db_name: demo_shared" in mongodb_config
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )


def test_non_interactive_requires_entity_when_multiple_models(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    _write_model(project_dir, "demo_service", "Recipe", "recipe")

    with pytest.raises(typer.Exit):
        add_adapter_cmd(project_dir=project_dir, adapter="memory", yes=True)
