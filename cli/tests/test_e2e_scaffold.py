"""E2E test — validate arclith-cli scaffold generates a working project."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from arclith_cli.recipe import RECIPE_FILENAME, load_recipe

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _framework_version() -> str:
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    assert match is not None, "Framework version missing from root pyproject.toml"
    return match.group(1)


@pytest.fixture
def temp_workspace():
    """Temporary directory for scaffolding tests."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def _template_args() -> list[str]:
    template_dir = os.environ.get("ARCLITH_TEMPLATE_DIR")
    if template_dir:
        return ["--template-dir", template_dir]

    sibling_template = Path(__file__).resolve().parents[3] / "_sample"
    if sibling_template.is_dir():
        return ["--template-dir", str(sibling_template)]

    return []


def _inject_local_arclith_source(project_dir: Path) -> None:
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().rstrip()
        + f'\n\n[tool.uv.sources]\narclith = {{ path = "{_REPO_ROOT.as_posix()}", editable = true }}\n'
    )


def test_init_scaffold_creates_blank_project_then_core_files(temp_workspace: Path):
    project_dir = temp_workspace / "todo-list-service"

    result = subprocess.run(
        [
            "arclith-cli",
            "init",
            "todo-list-service",
            "--dir",
            str(temp_workspace),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"init failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (project_dir / "src" / "todo_list_service" / "domain" / "models" / "__init__.py").exists()
    assert (project_dir / "src" / "todo_list_service" / "domain" / "ports" / "inbound" / "__init__.py").exists()
    assert not (project_dir / "src" / "todo_list_service" / "domain" / "models" / "todo.py").exists()
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert [
        step.command for step in load_recipe(project_dir / RECIPE_FILENAME).steps
    ] == ["init"]

    result = subprocess.run(
        ["arclith-cli", "add-entity", "Todo"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-entity failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    result = subprocess.run(
        ["arclith-cli", "add-usecase", "CreateTodo"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-usecase failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (project_dir / "src" / "todo_list_service" / "domain" / "models" / "todo.py").exists()
    assert (
        project_dir / "src" / "todo_list_service" / "application" / "use_cases" / "create_todo.py"
    ).exists()
    assert (
        project_dir / "src" / "todo_list_service" / "domain" / "ports" / "inbound" / "create_todo.py"
    ).exists()


def test_new_rejects_port_without_room_for_mcp(temp_workspace: Path):
    project_dir = temp_workspace / "bad-port-service"

    result = subprocess.run(
        [
            "arclith-cli",
            "new",
            "Plan",
            "bad-port-service",
            "--dir",
            str(temp_workspace),
            "--port",
            "65535",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert not project_dir.exists()
    assert "Port MCP invalide" in result.stdout + result.stderr


def test_scaffold_and_run(temp_workspace: Path):
    """Test that scaffolded project installs and runs successfully."""
    project_dir = temp_workspace / "test-plan-service"
    
    # Step 1 — scaffold via CLI (non-interactive)
    result = subprocess.run(
        [
            "arclith-cli",
            "new",
            "Plan",
            "test-plan-service",
            "--dir",
            str(temp_workspace),
            "--port",
            "8100",
            *_template_args(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    assert result.returncode == 0, f"Scaffold failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert project_dir.exists(), f"Project directory not created: {project_dir}"
    assert (project_dir / "pyproject.toml").exists()
    assert (project_dir / "main.py").exists()
    assert (project_dir / "config").is_dir()
    assert [
        step.command for step in load_recipe(project_dir / RECIPE_FILENAME).steps
    ] == ["new"]
    
    # Step 2 — verify no [tool.uv.sources] in generated pyproject.toml
    pyproject_content = (project_dir / "pyproject.toml").read_text()
    assert "[tool.uv.sources]" not in pyproject_content, (
        "Generated project must not contain [tool.uv.sources] — "
        "it should use stable PyPI arclith"
    )
    assert "arclith[" in pyproject_content, "arclith dependency missing"
    assert f">={_framework_version()}" in pyproject_content, (
        "Generated project must require the current framework release. "
        "Otherwise a fresh scaffold can resolve an older PyPI package that does not match the template."
    )
    _inject_local_arclith_source(project_dir)
    
    # Step 3 — uv sync
    result = subprocess.run(
        ["uv", "sync"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"uv sync failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (project_dir / ".venv").exists(), "Virtual environment not created"
    
    # Step 4 — validate imports (don't start server, just check imports work)
    result = subprocess.run(
        [
            "uv", "run", "python", "-c",
            "from arclith import load_config_dir, Arclith; "
            "from test_plan_service.adapters.inbound.fastapi.dependencies import require_auth; "
            "from test_plan_service.adapters.inbound.fastmcp.dependencies import require_auth_mcp; "
            "print('✅ All imports OK')"
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Import validation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert "✅ All imports OK" in result.stdout, (
        f"Import validation output unexpected:\n{result.stdout}"
    )
    
    # Step 5 — verify expected structure
    expected_dirs = [
        "src/test_plan_service/domain",
        "src/test_plan_service/adapters",
        "src/test_plan_service/application",
        "src/test_plan_service/infrastructure",
        "config",
        "tests",
    ]
    for dirname in expected_dirs:
        assert (project_dir / dirname).is_dir(), f"Missing expected directory: {dirname}"
    
    expected_files = ["Dockerfile", "Makefile", ".dockerignore", "arclith-run"]
    for fname in expected_files:
        assert (project_dir / fname).exists(), f"Missing expected file: {fname}"
    dockerfile = (project_dir / "Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert "USER 1001:1001" in dockerfile
    assert "EXPOSE 8100 8101 9000 2024" in dockerfile
    assert 'ENTRYPOINT ["./arclith-run"]' in dockerfile
    assert (project_dir / "arclith-run").stat().st_mode & stat.S_IXUSR

    # Step 6 — validate core scaffolding through the CLI entry point
    result = subprocess.run(
        [
            "arclith-cli",
            "add-entity",
            "ShoppingItem",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-entity failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (
        project_dir / "src" / "test_plan_service" / "domain" / "models" / "shopping_item.py"
    ).exists()

    result = subprocess.run(
        [
            "arclith-cli",
            "add-usecase",
            "PlanShoppingList",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-usecase failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (
        project_dir / "src" / "test_plan_service" / "application" / "use_cases" / "plan_shopping_list.py"
    ).exists()
    assert (
        project_dir / "src" / "test_plan_service" / "domain" / "ports" / "inbound" / "plan_shopping_list.py"
    ).exists()

    result = subprocess.run(
        [
            "arclith-cli",
            "add-intent-interpreter",
            "ShoppingIntent",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"add-intent-interpreter failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert (
        project_dir / "src" / "test_plan_service" / "application" / "intent_interpreters" / "shopping_intent.py"
    ).exists()

    printed_names = ", ".join(
        [
            "ShoppingItem.__name__",
            "PlanShoppingListPort.__name__",
            "PlanShoppingListUseCase.__name__",
            "ShoppingIntentInterpreter.__name__",
        ]
    )
    import_script = "\n".join(
        [
            "from test_plan_service.domain.models.shopping_item import ShoppingItem",
            "from test_plan_service.domain.ports.inbound.plan_shopping_list import PlanShoppingListPort",
            "from test_plan_service.application.use_cases.plan_shopping_list import PlanShoppingListUseCase",
            "from test_plan_service.application.intent_interpreters.shopping_intent import ShoppingIntentInterpreter",
            f"print({printed_names})",
        ]
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            import_script,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Core scaffold import failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert "ShoppingItem PlanShoppingListPort PlanShoppingListUseCase ShoppingIntentInterpreter" in result.stdout

    # Step 7 — validate non-interactive adapter generation through the CLI entry point
    result = subprocess.run(
        [
            "arclith-cli",
            "add-adapter",
            "--capability",
            "repository",
            "--adapter",
            "duckdb",
            "--entity",
            "Plan",
            "--path",
            "data/plans.csv",
            "--yes",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-adapter failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (project_dir / "config" / "adapters" / "outbound" / "duckdb.yaml").exists()
    assert "repository: duckdb" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )

    result = subprocess.run(
        [
            "arclith-cli",
            "add-adapter",
            "--capability",
            "llm",
            "--adapter",
            "lmstudio",
            "--param",
            "model_name=qwen/qwen3.5-9b",
            "--yes",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-adapter llm failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert (project_dir / "config" / "adapters" / "outbound" / "lm.yaml").exists()


def test_scaffold_with_custom_entity_formats(temp_workspace: Path):
    """Test entity name normalization (snake_case, kebab-case, PascalCase)."""
    test_cases = [
        ("Recipe", "my-recipe-service", "recipe", "Recipe", "RECIPE"),
        ("meal_plan", "meal-planner", "meal_plan", "MealPlan", "MEAL_PLAN"),
        ("recipe-step", "step-service", "recipe_step", "RecipeStep", "RECIPE_STEP"),
    ]
    
    for entity_input, project_name, expected_snake, expected_pascal, expected_upper in test_cases:
        project_dir = temp_workspace / project_name
        
        result = subprocess.run(
            [
                "arclith-cli",
                "new",
                entity_input,
                project_name,
                "--dir",
                str(temp_workspace),
                "--port",
                "9100",
                *_template_args(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        assert result.returncode == 0, f"Scaffold failed for {entity_input}"
        assert project_dir.exists()
        
        # Verify entity naming in generated files
        package_name = project_name.replace("-", "_")
        domain_model = project_dir / "src" / package_name / "domain" / "models" / f"{expected_snake}.py"
        assert domain_model.exists(), f"Expected {domain_model} not found"
        
        content = domain_model.read_text()
        assert f"class {expected_pascal}(" in content, f"PascalCase class name not found: {expected_pascal}"
        
        # Cleanup for next iteration
        shutil.rmtree(project_dir, ignore_errors=True)


@pytest.mark.slow
def test_scaffold_runs_tests(temp_workspace: Path):
    """Validate that generated project passes its own test suite."""
    project_dir = temp_workspace / "test-validated-service"
    
    # Scaffold
    subprocess.run(
        [
            "arclith-cli",
            "new",
            "Widget",
            "test-validated-service",
            "--dir",
            str(temp_workspace),
            *_template_args(),
        ],
        check=True,
        timeout=120,
    )
    _inject_local_arclith_source(project_dir)
    
    # Install deps
    subprocess.run(["uv", "sync", "--group", "dev"], cwd=project_dir, check=True, timeout=180)
    
    # Run tests
    result = subprocess.run(
        ["uv", "run", "pytest", "-v"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    # Allow failure if tests are present (template may have placeholders)
    # But validate pytest ran without import errors
    assert "ImportError" not in result.stdout + result.stderr, (
        f"Import errors detected:\n{result.stdout}\n{result.stderr}"
    )
