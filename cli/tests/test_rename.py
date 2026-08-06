from pathlib import Path
from importlib.metadata import version

from arclith_cli.rename import EntityNames, apply_rename


def test_apply_rename_updates_src_package_and_imports(tmp_path: Path):
    package_root = tmp_path / "src" / "arclith_sample" / "domain" / "models"
    package_root.mkdir(parents=True)
    model = package_root / "ingredient.py"
    model.write_text(
        "from arclith_sample.domain.models.ingredient import Ingredient\n"
        "class Ingredient: ...\n",
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        'name = "arclith-sample"\n'
        'packages = ["src/arclith_sample"]\n'
        'dependencies = ["arclith[all]>=0.12.0"]\n'
        "[tool.uv.sources]\n"
        'arclith = { path = "../arclith", editable = true }\n',
        encoding="utf-8",
    )

    apply_rename(tmp_path, EntityNames.from_input("Recipe"), project_name="my-recipe-service", port=8000)

    renamed_model = tmp_path / "src" / "my_recipe_service" / "domain" / "models" / "recipe.py"
    assert renamed_model.exists()
    assert "from my_recipe_service.domain.models.recipe import Recipe" in renamed_model.read_text(encoding="utf-8")
    patched_pyproject = pyproject.read_text(encoding="utf-8")
    assert 'name = "my-recipe-service"' in patched_pyproject
    assert 'packages = ["src/my_recipe_service"]' in patched_pyproject
    assert f'"arclith[all]>={version("arclith")}"' in patched_pyproject
    assert "[tool.uv.sources]" not in patched_pyproject
