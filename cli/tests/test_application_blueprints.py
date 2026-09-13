import ast
import asyncio
import importlib
import json
import re
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import pytest
import typer
import yaml
from typer.testing import CliRunner

from arclith_cli.application_blueprints import (
    application_blueprint_catalog_as_dict,
    get_application_blueprint,
)
from arclith_cli.application_blueprint_recipe import replay_add_entity_step
from arclith_cli.blueprint_generation import (
    add_application_blueprint_cmd,
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.entity_contract_ast import module_imports
from arclith_cli.feature_manifest import load_feature_manifest
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe

runner = CliRunner()
T = TypeVar("T")


def _project(tmp_path: Path, name: str = "blueprint-service") -> Path:
    project = init_project_cmd(project_name=name, directory=tmp_path)
    add_entity_cmd(project_dir=project, entity_name="Todo")
    return project


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    arguments: list[str],
    *,
    input_text: str | None = None,
):
    monkeypatch.chdir(project)
    return runner.invoke(app, arguments, input=input_text)


def test_crud_is_an_application_blueprint_not_an_adapter_capability() -> None:
    crud = get_application_blueprint("crud")

    assert crud.name == "crud"
    assert crud.operations == ("create", "get", "list", "update", "delete")
    assert application_blueprint_catalog_as_dict() == [
        {
            "name": "crud",
            "version": 1,
            "description": "Cycle de vie CRUD explicite pour une entité métier.",
            "operations": ["create", "get", "list", "update", "delete"],
        }
    ]


def test_crud_blueprint_generates_canonical_feature_layers(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )

    package = project / "src/blueprint_service"
    manifest_path = project / ".arclith/features/todo.yaml"
    manifest = load_feature_manifest(manifest_path)
    assert result.manifest_path == manifest_path
    assert manifest.feature == "todo"
    assert manifest.entity.name == "Todo"
    assert manifest.entity.module == "blueprint_service.domain.models.todo"
    assert manifest.blueprint.name == "crud"
    assert manifest.operations == ("create", "get", "list", "update", "delete")

    assert (package / "domain/errors/todo.py").is_file()
    for operation in manifest.operations:
        assert (package / f"domain/ports/inbound/{operation}_todo.py").is_file()
        assert (package / f"application/use_cases/{operation}_todo.py").is_file()
    assert (package / "infrastructure/containers/todo.py").is_file()
    assert (project / "tests/application/test_todo_crud.py").is_file()
    assert (project / "docs/blueprints/todo-crud.md").is_file()
    assert not (package / "adapters/inbound/fastapi").exists()
    assert not (package / "adapters/inbound/fastmcp").exists()


def test_crud_blueprint_snapshots_entity_business_fields(tmp_path: Path) -> None:
    project = _project(tmp_path, "inventory-service")
    entity = project / "src/inventory_service/domain/models/todo.py"
    entity.write_text(
        """from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from arclith.domain.models.entity import Entity

MIN_SKU_LENGTH = 3


class ProductStatus(StrEnum):
    ACTIVE = "active"


class Todo(Entity):
    collection: ClassVar[str] = "products"
    sku: str = Field(min_length=MIN_SKU_LENGTH, pattern=r"^[A-Z0-9-]+$")
    price: Decimal = Field(gt=0)
    stock: int = 0
    status: ProductStatus = ProductStatus.ACTIVE
""",
        encoding="utf-8",
    )

    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )

    ports = project / "src/inventory_service/domain/ports/inbound"
    create = (ports / "create_todo.py").read_text(encoding="utf-8")
    update = (ports / "update_todo.py").read_text(encoding="utf-8")
    generated_test = (project / "tests/application/test_todo_crud.py").read_text(
        encoding="utf-8"
    )

    assert "collection" not in create
    assert "from decimal import Decimal" in create
    assert "from pydantic import BaseModel, Field" in create
    assert "from inventory_service.domain.models.todo import (" not in create
    assert "from inventory_service.domain.models.todo import MIN_SKU_LENGTH" in create
    assert "ProductStatus" in create
    assert (
        "sku: str = Field(min_length=MIN_SKU_LENGTH, pattern='^[A-Z0-9-]+$')" in create
    )
    assert "price: Decimal = Field(gt=0)" in create
    assert "stock: int = 0" in create
    assert "status: ProductStatus = ProductStatus.ACTIVE" in create
    assert "sku: str = Field(default=None, min_length=MIN_SKU_LENGTH" in update
    assert "price: Decimal = Field(default=None, gt=0)" in update
    assert "stock: int = Field(default=None)" in update
    assert "status: ProductStatus = Field(default=None)" in update
    assert "CreateTodoCommand.model_fields" in generated_test
    assert "CreateTodoCommand()" not in generated_test


def test_crud_blueprint_replays_without_overwriting_developer_files(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    first = plan_application_blueprint(
        project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
    )
    apply_application_blueprint(first)
    create_use_case = (
        project / "src/blueprint_service/application/use_cases/create_todo.py"
    )
    create_use_case.write_text(
        create_use_case.read_text(encoding="utf-8") + "\n# developer rule\n",
        encoding="utf-8",
    )

    replay = plan_application_blueprint(
        project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
    )
    changed = apply_application_blueprint(replay)

    assert changed == ()
    assert create_use_case.read_text(encoding="utf-8").endswith("# developer rule\n")
    assert create_use_case in replay.preserved


def test_crud_blueprint_rejects_a_changed_canonical_manifest(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    manifest_path = project / ".arclith/features/todo.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["operations"] = ["create", "get"]
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="different canonical manifest"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
        )


@pytest.mark.parametrize(
    ("feature", "message"),
    [
        ("todo-item", "public Python identifier"),
        ("class", "public Python identifier"),
    ],
)
def test_feature_manifest_rejects_an_invalid_feature_identifier(
    tmp_path: Path,
    feature: str,
    message: str,
) -> None:
    manifest_path = tmp_path / "feature.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "feature": feature,
                "entity": {"name": "Todo", "module": "demo.domain.models.todo"},
                "blueprint": {"name": "crud", "version": 1},
                "operations": ["create"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_feature_manifest(manifest_path)


def test_feature_manifest_rejects_a_boolean_schema_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / "feature.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": True,
                "feature": "todo",
                "entity": {"name": "Todo", "module": "demo.domain.models.todo"},
                "blueprint": {"name": "crud", "version": 1},
                "operations": ["create"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="feature.version must be an integer"):
        load_feature_manifest(manifest_path)


def test_feature_manifest_reports_malformed_yaml_as_a_validation_error(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "feature.yaml"
    manifest_path.write_text("version: [unterminated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid YAML in feature manifest"):
        load_feature_manifest(manifest_path)


def test_crud_blueprint_dry_run_has_no_filesystem_or_recipe_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    result = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "crud", "--entity", "Todo", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (project / "arclith.recipe.yaml").exists()
    assert not (project / ".arclith/features/todo.yaml").exists()


def test_crud_blueprint_rejects_a_first_install_collision_without_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    conflict = project / "src/blueprint_service/application/use_cases/create_todo.py"
    conflict.write_text("# existing\n", encoding="utf-8")
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="already exists"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
        )

    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (project / ".arclith/features/todo.yaml").exists()


def test_crud_blueprint_rejects_a_manifest_directory_without_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    manifest_path = project / ".arclith/features/todo.yaml"
    manifest_path.mkdir(parents=True)
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="target is not a file"):
        plan_application_blueprint(
            project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
        )

    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not (
        project / "src/blueprint_service/application/use_cases/create_todo.py"
    ).exists()


def test_crud_blueprint_executes_the_framework_crud_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "runtime-blueprint-service")
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    monkeypatch.syspath_prepend(str(project / "src"))
    container = importlib.import_module(
        "runtime_blueprint_service.infrastructure.containers.todo"
    )
    contracts = {
        operation: importlib.import_module(
            f"runtime_blueprint_service.domain.ports.inbound.{operation}_todo"
        )
        for operation in ("create", "get", "list", "update", "delete")
    }
    from arclith import Arclith

    use_cases = container.build_todo_use_cases(Arclith(project / "config"))
    created = _run(
        use_cases.create.execute(contracts["create"].CreateTodoCommand())
    ).item
    assert created.version == 1

    found = _run(
        use_cases.get.execute(contracts["get"].GetTodoQuery(uuid=created.uuid))
    )
    assert found.item == created

    page = _run(use_cases.list.execute(contracts["list"].ListTodoQuery()))
    assert page.items == [created]
    assert page.total == 1

    updated = _run(
        use_cases.update.execute(
            contracts["update"].UpdateTodoCommand(
                uuid=created.uuid,
                version=created.version,
            )
        )
    ).item
    assert updated.version == 2

    with pytest.raises(
        importlib.import_module(
            "runtime_blueprint_service.domain.errors.todo"
        ).TodoVersionConflictError
    ):
        _run(
            use_cases.update.execute(
                contracts["update"].UpdateTodoCommand(
                    uuid=created.uuid,
                    version=created.version,
                )
            )
        )

    deleted = _run(
        use_cases.delete.execute(
            contracts["delete"].DeleteTodoCommand(uuid=created.uuid)
        )
    )
    assert deleted.deleted is True
    with pytest.raises(
        importlib.import_module(
            "runtime_blueprint_service.domain.errors.todo"
        ).TodoNotFoundError
    ):
        _run(use_cases.get.execute(contracts["get"].GetTodoQuery(uuid=created.uuid)))

    for module in tuple(sys.modules):
        if module == "runtime_blueprint_service" or module.startswith(
            "runtime_blueprint_service."
        ):
            sys.modules.pop(module)


def test_crud_blueprint_executes_aliased_business_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "aliased-blueprint-service")
    entity = project / "src/aliased_blueprint_service/domain/models/todo.py"
    entity.write_text(
        '''from typing import Annotated, ClassVar as CV

import pydantic.fields
from pydantic import BaseModel, ConfigDict, Field, fields as pf

from arclith.domain.models.entity import Entity

type ProductCode = str


class RelatedProduct(BaseModel):
    code: str


class Todo(Entity):
    model_config = ConfigDict(extra="allow")
    MIN_SKU_LENGTH: CV[int] = 3
    sku: ProductCode = Field(
        alias="productSku",
        serialization_alias="publicSku",
        min_length=MIN_SKU_LENGTH,
        exclude=True,
    )
    slug: str = Field(
        default_factory=lambda data: data["sku"].lower(),
        validate_default=True,
    )
    related: "RelatedProduct | None" = None
    secret_code: "Annotated[str, Field(exclude=True, min_length=2)]"
    tracking_code: str = pydantic.fields.Field(exclude=True, min_length=2)
    alternate_tracking_code: str = pf.Field(exclude=True, min_length=2)
    deferred_code: "Annotated[str, Field(min_length=MIN_SKU_LENGTH)]"
    external_id: str = Field(default_factory=lambda data: str(data["uuid"]))
''',
        encoding="utf-8",
    )
    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )
    monkeypatch.syspath_prepend(str(project / "src"))
    container = importlib.import_module(
        "aliased_blueprint_service.infrastructure.containers.todo"
    )
    create_contract = importlib.import_module(
        "aliased_blueprint_service.domain.ports.inbound.create_todo"
    )
    update_contract = importlib.import_module(
        "aliased_blueprint_service.domain.ports.inbound.update_todo"
    )
    create_source = (
        project
        / "src/aliased_blueprint_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    update_source = (
        project
        / "src/aliased_blueprint_service/domain/ports/inbound/update_todo.py"
    ).read_text(encoding="utf-8")
    from arclith import Arclith

    use_cases = container.build_todo_use_cases(Arclith(project / "config"))
    assert "Todo.MIN_SKU_LENGTH" in create_source
    assert "exclude=True" not in create_source
    assert "serialization_alias" not in create_source
    assert "default_factory" not in create_source
    assert "default_factory" not in update_source
    assert "validate_default=True" not in update_source
    assert set(create_contract.CreateTodoCommand.model_fields) == {
        "related",
        "secret_code",
        "sku",
        "slug",
        "tracking_code",
        "alternate_tracking_code",
        "deferred_code",
        "external_id",
    }
    request = create_contract.CreateTodoCommand.model_validate(
        {
            "productSku": "SKU-001",
            "secret_code": "S3",
            "tracking_code": "T3",
            "alternate_tracking_code": "A3",
            "deferred_code": "DEF",
        }
    )
    assert "productSku" in request.model_dump(by_alias=True)
    assert "publicSku" not in request.model_dump(by_alias=True)
    assert (
        create_contract.CreateTodoCommand.model_fields["related"].annotation
        == create_contract.RelatedProduct | None
    )
    created = _run(
        use_cases.create.execute(
            request
        )
    ).item
    created.legacy_code = "keep-me"
    unchanged = _run(
        use_cases.update.execute(
            update_contract.UpdateTodoCommand(
                uuid=created.uuid,
                version=created.version,
            )
        )
    ).item
    updated = _run(
        use_cases.update.execute(
            update_contract.UpdateTodoCommand.model_validate(
                {
                    "uuid": created.uuid,
                    "version": unchanged.version,
                    "productSku": "SKU-002",
                }
            )
        )
    ).item

    assert created.sku == "SKU-001"
    assert created.slug == "sku-001"
    assert created.secret_code == "S3"
    assert created.tracking_code == "T3"
    assert created.alternate_tracking_code == "A3"
    assert created.deferred_code == "DEF"
    assert created.external_id == str(created.uuid)
    assert unchanged.sku == "SKU-001"
    assert unchanged.model_extra == {"legacy_code": "keep-me"}
    assert updated.sku == "SKU-002"
    assert updated.version == 3

    for module in tuple(sys.modules):
        if module == "aliased_blueprint_service" or module.startswith(
            "aliased_blueprint_service."
        ):
            sys.modules.pop(module)


def test_crud_blueprint_resolves_type_checking_imports(tmp_path: Path) -> None:
    project = _project(tmp_path, "deferred-blueprint-service")
    models = project / "src/deferred_blueprint_service/domain/models"
    (models / "product_types.py").write_text("type Money = int\n", encoding="utf-8")
    (models / "todo.py").write_text(
        '''from __future__ import annotations

from typing import TYPE_CHECKING

from arclith.domain.models.entity import Entity

if TYPE_CHECKING:
    from .product_types import Money


class Todo(Entity):
    price: Money
''',
        encoding="utf-8",
    )

    add_application_blueprint_cmd(
        project_dir=project,
        blueprint_name="crud",
        entity_name="Todo",
        feature_name="todo",
        dry_run=False,
    )

    create_source = (
        project
        / "src/deferred_blueprint_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    assert (
        "from deferred_blueprint_service.domain.models.product_types import Money"
        in create_source
    )


def test_module_imports_do_not_flatten_runtime_conditionals() -> None:
    tree = ast.parse(
        '''import sys
from typing import TYPE_CHECKING as TC

if TC:
    from .product_types import Money

if sys.version_info >= (3, 13):
    from .new_runtime import RuntimeType
else:
    from .legacy_runtime import RuntimeType

try:
    import optional_dependency
except ImportError:
    optional_dependency = None
'''
    )

    assert {ast.unparse(statement) for statement in module_imports(tree)} == {
        "import sys",
        "from typing import TYPE_CHECKING as TC",
        "from .product_types import Money",
    }


def _run(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_blueprints_command_and_add_blueprint_are_recipe_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)

    catalogue = _invoke(monkeypatch, project, ["blueprints", "--json"])
    assert catalogue.exit_code == 0, catalogue.output
    assert json.loads(catalogue.output)[0]["name"] == "crud"

    generated = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "crud", "--entity", "Todo", "--feature", "todo"],
    )
    assert generated.exit_code == 0, generated.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[-1].command == "add-blueprint"
    assert recipe.steps[-1].args["blueprint"] == "crud"
    assert recipe.steps[-1].args["entity"] == "Todo"
    assert recipe.steps[-1].args["feature"] == "todo"
    assert recipe.steps[-1].args["operations"] == [
        "create",
        "get",
        "list",
        "update",
        "delete",
    ]

    replay_target = tmp_path / "blueprint-replay"
    init_project_cmd(
        project_name="blueprint-service",
        target_path=replay_target,
    )
    add_entity_cmd(project_dir=replay_target, entity_name="Todo")
    replay_recipe(recipe, (recipe.steps[-1],), target_dir=replay_target, strict=True)
    assert (replay_target / ".arclith/features/todo.yaml").is_file()


def test_add_entity_crud_profile_is_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = runner.invoke(
        app,
        ["init", "profile-service", "--dir", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project = tmp_path / "profile-service"

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Todo", "--profile", "crud"],
    )
    assert result.exit_code == 0, result.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[-1].command == "add-entity"
    assert recipe.steps[-1].args["entity"] == "Todo"
    assert recipe.steps[-1].args["profile"] == "crud"
    assert recipe.steps[-1].args["blueprint_version"] == 1
    assert recipe.steps[-1].args["operations"] == [
        "create",
        "get",
        "list",
        "update",
        "delete",
    ]
    assert re.fullmatch(
        r"sha256:[a-f0-9]{64}", recipe.steps[-1].args["template_digest"]
    )

    replay_target = tmp_path / "profile-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    manifest = yaml.safe_load(
        (replay_target / ".arclith/features/todo.yaml").read_text(encoding="utf-8")
    )
    assert manifest["blueprint"]["name"] == "crud"
    assert manifest["operations"] == ["create", "get", "list", "update", "delete"]


def test_new_accepts_and_replays_the_crud_profile(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        [
            "new",
            "Todo",
            "new-crud-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "crud",
        ],
    )
    assert created.exit_code == 0, created.output
    project = tmp_path / "new-crud-service"
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert recipe.steps[0].args["profile"] == "crud"
    assert recipe.steps[0].args["blueprint_version"] == 1
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", recipe.steps[0].args["template_digest"])
    assert (project / ".arclith/features/todo.yaml").is_file()

    replay_target = tmp_path / "new-crud-replay"
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    assert (replay_target / ".arclith/features/todo.yaml").is_file()


def test_add_entity_interactive_profile_choice_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="interactive-service", directory=tmp_path)

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity"],
        input_text="Todo\n2\n",
    )

    assert result.exit_code == 0, result.output
    assert "Profil applicatif initial" in result.output
    assert (project / ".arclith/features/todo.yaml").is_file()


def test_add_entity_direct_mode_keeps_the_minimal_profile_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="minimal-service", directory=tmp_path)

    result = _invoke(monkeypatch, project, ["add-entity", "Todo"])

    assert result.exit_code == 0, result.output
    assert not (project / ".arclith/features/todo.yaml").exists()
    assert load_recipe(project / "arclith.recipe.yaml").steps[-1].args == {
        "entity": "Todo",
        "profile": "minimal",
    }


def test_unknown_blueprint_and_profile_fail_without_partial_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = init_project_cmd(project_name="invalid-service", directory=tmp_path)

    with pytest.raises(ValueError, match="Unknown application blueprint"):
        get_application_blueprint("unknown")

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Todo", "--profile", "unknown"],
    )
    assert result.exit_code == 1
    assert not (project / "src/invalid_service/domain/models/todo.py").exists()
    assert not (project / ".arclith/features/todo.yaml").exists()

    new_result = runner.invoke(
        app,
        [
            "new",
            "Todo",
            "invalid-new-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "unknown",
        ],
    )
    assert new_result.exit_code == 1
    assert not (tmp_path / "invalid-new-service").exists()


@pytest.mark.parametrize("profile", ["minimal", "crud"])
def test_add_entity_rejects_python_keyword_names_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    project = init_project_cmd(project_name="keyword-service", directory=tmp_path)

    result = _invoke(
        monkeypatch,
        project,
        ["add-entity", "Class", "--profile", profile],
    )

    assert result.exit_code == 1
    assert (
        "mot-clé Python réservé" in result.output
        or "reserved Python keyword" in result.output
    )
    assert not (project / "src/keyword_service/domain/models/class.py").exists()
    assert not (project / ".arclith/features/class.yaml").exists()


def test_crud_profile_recipe_preflights_collisions_before_entity_creation(
    tmp_path: Path,
) -> None:
    project = init_project_cmd(project_name="recipe-service", directory=tmp_path)
    collision = project / "src/recipe_service/application/use_cases/create_todo.py"
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("# developer-owned\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        replay_add_entity_step(
            project,
            {"entity": "Todo", "profile": "crud"},
        )

    assert not (project / "src/recipe_service/domain/models/todo.py").exists()
    assert collision.read_text(encoding="utf-8") == "# developer-owned\n"


def test_crud_profile_recipe_validates_profile_before_entity_creation(
    tmp_path: Path,
) -> None:
    project = init_project_cmd(project_name="recipe-service", directory=tmp_path)

    with pytest.raises(ValueError, match="Unknown application blueprint"):
        replay_add_entity_step(
            project,
            {"entity": "Todo", "profile": "unknown"},
        )

    assert not (project / "src/recipe_service/domain/models/todo.py").exists()


def test_add_blueprint_requires_an_existing_entity(tmp_path: Path) -> None:
    project = init_project_cmd(project_name="empty-service", directory=tmp_path)

    with pytest.raises(typer.Exit):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )
