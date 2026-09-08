"""Contract, preservation and runtime tests for complete adapter blueprints."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from arclith.infrastructure.project_layout import canonical_project_layout
from arclith_cli.adapter_blueprints import (
    blueprint_digest,
    get_adapter_blueprint,
    render_adapter_blueprint,
    render_feature_blueprint,
    validate_adapter_blueprint,
    write_missing_files,
)
from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.capabilities import CAPABILITY_CATALOG, AGENT_CAPABILITY
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.init_project import init_project_cmd


@pytest.mark.parametrize("capability", CAPABILITY_CATALOG, ids=lambda item: item.name)
def test_every_catalog_adapter_has_a_complete_compilable_blueprint(
    capability, tmp_path: Path
) -> None:
    for adapter in capability.adapters:
        blueprint = get_adapter_blueprint(adapter)
        rendered = render_adapter_blueprint(blueprint, "test_service")
        root = tmp_path / adapter.name
        write_missing_files(root, rendered)
        assert validate_adapter_blueprint(root, blueprint) == ()
        assert blueprint.version == "1"
        assert blueprint_digest(blueprint).startswith("sha256:")
        for path, content in rendered.items():
            if path.endswith(".py"):
                ast.parse(content, filename=path)
        for role in blueprint.roles:
            assert f"{role}/README.md" in rendered
            assert f"{role}/__init__.py" in rendered
        if capability.name == "mcp":
            assert all(
                f"features/example/{role}/README.md" in rendered
                for role in ("tools", "resources", "prompts")
            )


def test_blueprint_replay_preserves_code_and_restores_missing_files(
    tmp_path: Path,
) -> None:
    blueprint = get_adapter_blueprint(AGENT_CAPABILITY.adapters[0])
    rendered = render_adapter_blueprint(blueprint, "test_service")
    write_missing_files(tmp_path, rendered)
    graph = tmp_path / "graph.py"
    graph.write_text('"""User-authored graph topology."""\n', encoding="utf-8")
    (tmp_path / "nodes" / "README.md").unlink()
    created = write_missing_files(tmp_path, rendered)
    assert created == (tmp_path / "nodes" / "README.md",)
    assert graph.read_text(encoding="utf-8") == '"""User-authored graph topology."""\n'
    assert validate_adapter_blueprint(tmp_path, blueprint) == ()
    assert write_missing_files(tmp_path, rendered) == ()


def test_complete_feature_names_cannot_escape_the_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="identifier"):
        render_feature_blueprint("api", "../../outside", "test_service")
    with pytest.raises(ValueError, match="Unsafe"):
        write_missing_files(tmp_path, {"../outside.py": ""})


def test_init_obeys_layout_and_creates_all_native_roles(tmp_path: Path) -> None:
    root = init_project_cmd(project_name="blueprint-service", directory=tmp_path)
    layout = canonical_project_layout("blueprint_service")
    assert all(
        (root / path / "__init__.py").is_file()
        for path in layout.scaffold_directories()
    )
    assert (root / "AGENTS.md").is_file()
    fastapi = root / layout.inbound_adapters / "fastapi"
    fastmcp = root / layout.inbound_adapters / "fastmcp"
    assert (fastapi / "routers/v1/example/openapi.py").is_file()
    assert (fastapi / "routers/v1/example/routes/README.md").is_file()
    assert (fastmcp / "features/example/prompts/README.md").is_file()
    assert (fastmcp / "features/example/resources/README.md").is_file()
    assert (fastmcp / "features/example/tools/README.md").is_file()


def test_dry_run_leaves_the_project_unchanged(tmp_path: Path) -> None:
    root = init_project_cmd(project_name="dry-service", directory=tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    add_adapter_cmd(
        project_dir=root,
        capability_name="agent",
        adapter="langgraph",
        yes=True,
        dry_run=True,
    )
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_legacy_module_shadowing_fails_before_any_write(tmp_path: Path) -> None:
    root = init_project_cmd(project_name="legacy-service", directory=tmp_path)
    adapter = root / "src/legacy_service/adapters/inbound/langgraph"
    adapter.mkdir()
    legacy = adapter / "nodes.py"
    legacy.write_text('"""Existing application nodes."""\n', encoding="utf-8")
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError, match="Migrate legacy modules"):
        add_adapter_cmd(
            project_dir=root, capability_name="agent", adapter="langgraph", yes=True
        )
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_incremental_multi_entity_repositories_import_and_preserve_customizations(
    tmp_path: Path,
) -> None:
    root = init_project_cmd(project_name="repository-service", directory=tmp_path)
    for name in ("Todo", "Label"):
        add_entity_cmd(project_dir=root, entity_name=name)
    add_adapter_cmd(project_dir=root, adapter="memory", all_entities=True, yes=True)
    package = root / "src/repository_service"
    repository = package / "adapters/outbound/memory/repositories/todo_repository.py"
    original = repository.read_text(encoding="utf-8") + "\n# User customization\n"
    repository.write_text(original, encoding="utf-8")
    container = package / "infrastructure/containers/todo_container.py"
    customized = container.read_text(encoding="utf-8") + "\n# Custom composition\n"
    container.write_text(customized, encoding="utf-8")
    add_adapter_cmd(project_dir=root, adapter="memory", all_entities=True, yes=True)
    assert repository.read_text(encoding="utf-8") == original
    assert container.read_text(encoding="utf-8") == customized
    assert not (package / "adapters/outbound/memory/repository.py").exists()
    source = """
from arclith import Arclith
from repository_service.adapters.outbound.memory.repositories.todo_repository import InMemoryTodoRepository
from repository_service.adapters.outbound.memory.repositories.label_repository import InMemoryLabelRepository
from repository_service.infrastructure.containers.todo_container import build_todo_service
from repository_service.infrastructure.containers.label_container import build_label_service
app = Arclith("config")
assert InMemoryTodoRepository is not InMemoryLabelRepository
assert build_todo_service(app)[0] is not None
assert build_label_service(app)[0] is not None
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_generated_langgraph_compiles_and_invokes_without_services(
    tmp_path: Path,
) -> None:
    root = init_project_cmd(project_name="graph-service", directory=tmp_path)
    add_adapter_cmd(
        project_dir=root, capability_name="agent", adapter="langgraph", yes=True
    )
    source = """
import asyncio
from graph_service.adapters.inbound.langgraph.agent import agent
result = asyncio.run(agent.ainvoke({"messages": []}))
assert result["state_version"] == 1
assert result["messages"] == []
assert {"example"} <= set(agent.get_graph().nodes)
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
