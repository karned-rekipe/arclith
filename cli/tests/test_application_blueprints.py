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
from arclith_cli.module_bindings import module_imports
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
            "parameterized": False,
        },
        {
            "name": "append-only",
            "version": 1,
            "description": (
                "Faits immuables avec append idempotent et conflit explicite."
            ),
            "operations": ["append"],
            "parameterized": False,
        },
        {
            "name": "state-machine",
            "version": 1,
            "description": (
                "Cycle de vie typé avec transitions métier définies par une spec."
            ),
            "operations": [],
            "parameterized": True,
        },
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


def test_crud_blueprint_snapshots_entity_business_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "inventory-service")
    entity = project / "src/inventory_service/domain/models/todo.py"
    entity.write_text(
        """from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Final as F

from pydantic import Field

from arclith.domain.models.entity import Entity

MIN_SKU_LENGTH = 3


class ProductStatus(StrEnum):
    ACTIVE = "active"


class Todo(Entity):
    collection: ClassVar[str] = "products"
    category: F[str] = "catalog"
    sku: str = Field(min_length=MIN_SKU_LENGTH, pattern=r"^[A-Z0-9-]+$")
    price: Decimal = Field(gt=0)
    stock: int = 0
    status: ProductStatus = ProductStatus.ACTIVE
    frozen_code: F[str]
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
    generated_docs = (project / "docs/blueprints/todo-crud.md").read_text(
        encoding="utf-8"
    )

    assert "collection" not in create
    assert "category" not in create
    assert "from decimal import Decimal" in create
    assert "from pydantic import BaseModel as _ArclithCrudBaseModel, Field" in create
    assert "from inventory_service.domain.models.todo import (" not in create
    assert "MIN_SKU_LENGTH = 3" in create
    assert "ProductStatus" in create
    assert (
        "sku: str = Field(min_length=MIN_SKU_LENGTH, pattern='^[A-Z0-9-]+$')" in create
    )
    assert "price: Decimal = Field(gt=0)" in create
    assert "stock: int = 0" in create
    assert "status: ProductStatus = ProductStatus.ACTIVE" in create
    assert "frozen_code: F[str]" in create
    assert "frozen_code" not in update
    assert "sku: str = Field(default=None, min_length=MIN_SKU_LENGTH" in update
    assert "price: Decimal = Field(default=None, gt=0)" in update
    assert "stock: int = _ArclithCrudField(default=None)" in update
    assert "status: ProductStatus = _ArclithCrudField(default=None)" in update
    assert "CreateTodoCommand.model_fields" in generated_test
    assert "CreateTodoCommand()" not in generated_test
    assert "Les champs modifiables `sku`, `price`, `stock`, `status`" in generated_docs
    assert "`frozen_code` restent réservés à la création" in generated_docs
    assert "Les champs modifiables `frozen_code`" not in generated_docs

    monkeypatch.syspath_prepend(str(project / "src"))
    create_contract = importlib.import_module(
        "inventory_service.domain.ports.inbound.create_todo"
    )
    update_contract = importlib.import_module(
        "inventory_service.domain.ports.inbound.update_todo"
    )
    assert "frozen_code" in create_contract.CreateTodoCommand.model_fields
    assert "frozen_code" not in update_contract.UpdateTodoCommand.model_fields
    for module in tuple(sys.modules):
        if module == "inventory_service" or module.startswith("inventory_service."):
            sys.modules.pop(module)


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
        """from typing import Annotated as A, ClassVar as CV

import pydantic.fields
from pydantic import AliasPath, BaseModel, ConfigDict, Field, fields as pf

from arclith.domain.models.entity import Entity

type ProductCode = str


class RelatedProduct(BaseModel):
    code: str


class Todo(Entity):
    model_config = ConfigDict(extra="allow")
    collection: "CV[str]" = "todos"
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
    secret_code: "A[str, Field(exclude=True, min_length=2)]"
    tracking_code: str = pydantic.fields.Field(exclude=True, min_length=2)
    alternate_tracking_code: str = pf.Field(exclude=True, min_length=2)
    deferred_code: "A[str, Field(min_length=MIN_SKU_LENGTH)]"
    external_id: str = Field(default_factory=lambda data: str(data["uuid"]))
    annotated_external_id: A[
        str,
        pf.Field(default_factory=lambda data: str(data["uuid"])),
    ]
    nested_code: str = Field(validation_alias=AliasPath("payload", "uuid"))
    note: str = "Field(alias='uuid', default_factory=make_note)"
    string_metadata: A[
        str,
        "Field(alias='uuid', default_factory=make_note)",
    ]
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
        project / "src/aliased_blueprint_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    update_source = (
        project / "src/aliased_blueprint_service/domain/ports/inbound/update_todo.py"
    ).read_text(encoding="utf-8")
    from arclith import Arclith

    use_cases = container.build_todo_use_cases(Arclith(project / "config"))
    assert "Todo.MIN_SKU_LENGTH" in create_source
    deferred_field = next(
        node
        for node in ast.walk(ast.parse(create_source))
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "deferred_code"
    )
    assert isinstance(deferred_field.annotation, ast.Constant)
    assert "Todo.MIN_SKU_LENGTH" in deferred_field.annotation.value
    assert "exclude=True" not in create_source
    assert "serialization_alias" not in create_source
    assert not any(
        isinstance(node, ast.keyword) and node.arg == "default_factory"
        for node in ast.walk(ast.parse(create_source))
    )
    assert not any(
        isinstance(node, ast.keyword) and node.arg == "default_factory"
        for node in ast.walk(ast.parse(update_source))
    )
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
        "annotated_external_id",
        "nested_code",
        "note",
        "string_metadata",
    }
    request = create_contract.CreateTodoCommand.model_validate(
        {
            "productSku": "SKU-001",
            "secret_code": "S3",
            "tracking_code": "T3",
            "alternate_tracking_code": "A3",
            "deferred_code": "DEF",
            "payload": {"uuid": "N3"},
            "string_metadata": "opaque",
        }
    )
    assert "productSku" in request.model_dump(by_alias=True)
    assert "publicSku" not in request.model_dump(by_alias=True)
    assert (
        create_contract.CreateTodoCommand.model_fields["related"].annotation
        == create_contract.RelatedProduct | None
    )
    created = _run(use_cases.create.execute(request)).item
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
    assert created.annotated_external_id == str(created.uuid)
    assert created.nested_code == "N3"
    assert created.note == "Field(alias='uuid', default_factory=make_note)"
    assert created.string_metadata == "opaque"
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
        """from __future__ import annotations

from typing import TYPE_CHECKING

from arclith.domain.models.entity import Entity

if TYPE_CHECKING:
    from .product_types import Money


class Todo(Entity):
    price: Money
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

    create_source = (
        project / "src/deferred_blueprint_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    assert (
        "from deferred_blueprint_service.domain.models.product_types import Money"
        in create_source
    )


def test_crud_blueprint_imports_project_type_shadowing_builtin(tmp_path: Path) -> None:
    project = _project(tmp_path, "shadowed-builtin-service")
    entity = project / "src/shadowed_builtin_service/domain/models/todo.py"
    entity.write_text(
        """from arclith.domain.models.entity import Entity


class CustomType(str):
    pass


list = CustomType


class Todo(Entity):
    value: list
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

    create_source = (
        project / "src/shadowed_builtin_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    assert (
        "from shadowed_builtin_service.domain.models.todo import Todo, list"
        in create_source
    )


@pytest.mark.parametrize(
    ("alias", "message"),
    (
        ('alias="uuid"', "collide with technical CRUD fields"),
        ('validation_alias="version"', "collide with technical CRUD fields"),
        ("alias=INPUT_KEY", "cannot be resolved statically"),
    ),
)
def test_crud_blueprint_rejects_technical_input_alias_collisions(
    tmp_path: Path,
    alias: str,
    message: str,
) -> None:
    project = _project(tmp_path, "colliding-alias-service")
    entity = project / "src/colliding_alias_service/domain/models/todo.py"
    entity.write_text(
        f"""from pydantic import Field

from arclith.domain.models.entity import Entity

INPUT_KEY = "uuid"


class Todo(Entity):
    external_id: str = Field({alias})
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "alias_declaration",
    (
        'AliasPath("payload", shared_contracts.KEY)',
        'AliasPath("payload", dynamic_segment())',
        'AliasPath("payload", **OPTIONS)',
    ),
)
def test_crud_blueprint_rejects_dynamic_alias_path_segments(
    tmp_path: Path,
    alias_declaration: str,
) -> None:
    project = _project(tmp_path, "dynamic-alias-path-service")
    entity = project / "src/dynamic_alias_path_service/domain/models/todo.py"
    entity.write_text(
        f"""import shared_contracts
from pydantic import AliasPath, Field

from arclith.domain.models.entity import Entity

OPTIONS = {{"path": "uuid"}}


def dynamic_segment() -> str:
    return "uuid"


class Todo(Entity):
    code: str = Field(validation_alias={alias_declaration})
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be resolved statically"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    ("constructor", "arguments"),
    (
        ("AliasPath", '"payload", "uuid"'),
        ("AliasChoices", '"publicCode", "uuid"'),
    ),
)
def test_crud_blueprint_rejects_fake_alias_constructor(
    tmp_path: Path,
    constructor: str,
    arguments: str,
) -> None:
    project = _project(tmp_path, "fake-alias-path-service")
    entity = project / "src/fake_alias_path_service/domain/models/todo.py"
    entity.write_text(
        f"""from pydantic import Field

from arclith.domain.models.entity import Entity


def {constructor}(*segments: str) -> tuple[str, ...]:
    return segments


class Todo(Entity):
    code: str = Field(validation_alias={constructor}({arguments}))
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be resolved statically"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "alias_declaration",
    (
        'AliasChoices("uuid", "publicCode")',
        'AliasChoices(AliasPath("version", "nested"), "publicCode")',
    ),
)
def test_crud_blueprint_resolves_pydantic_alias_choices(
    tmp_path: Path,
    alias_declaration: str,
) -> None:
    project = _project(tmp_path, "alias-choices-service")
    entity = project / "src/alias_choices_service/domain/models/todo.py"
    entity.write_text(
        f"""from pydantic import AliasChoices, AliasPath, Field

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: str = Field(validation_alias={alias_declaration})
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="collide with technical CRUD fields"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_entity_alias_generators(tmp_path: Path) -> None:
    project = _project(tmp_path, "generated-alias-service")
    entity = project / "src/generated_alias_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import ConfigDict

from arclith.domain.models.entity import Entity


def to_camel(value: str) -> str:
    return value


class Todo(Entity):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="alias_generator.*cannot be projected"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_legacy_config_alias_generators(tmp_path: Path) -> None:
    project = _project(tmp_path, "legacy-alias-service")
    entity = project / "src/legacy_alias_service/domain/models/todo.py"
    entity.write_text(
        """from arclith.domain.models.entity import Entity


class Todo(Entity):
    class Config:
        alias_generator = str.upper

    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="legacy Config.*alias_generator"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_conditional_pydantic_rebinding(tmp_path: Path) -> None:
    project = _project(tmp_path, "conditional-field-service")
    entity = project / "src/conditional_field_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import Field

from arclith.domain.models.entity import Entity

USE_CUSTOM = False
if USE_CUSTOM:
    Field = object


class Todo(Entity):
    external_id: str = Field(alias="uuid")
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="control flow.*Field"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "class_options",
    ("alias_generator=to_camel", "**CLASS_CONFIG"),
)
def test_crud_blueprint_rejects_class_keyword_alias_generators(
    tmp_path: Path,
    class_options: str,
) -> None:
    project = _project(tmp_path, "class-alias-service")
    entity = project / "src/class_alias_service/domain/models/todo.py"
    entity.write_text(
        f"""from arclith.domain.models.entity import Entity


def to_camel(value: str) -> str:
    return value


CLASS_CONFIG = {{"alias_generator": to_camel}}


class Todo(Entity, {class_options}):
    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="class.*alias_generator"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "configuration",
    ("ConfigDict(**ALIAS_CONFIG)", "ConfigDict(ALIAS_CONFIG)"),
)
def test_crud_blueprint_rejects_indirect_model_config(
    tmp_path: Path,
    configuration: str,
) -> None:
    project = _project(tmp_path, "indirect-config-service")
    entity = project / "src/indirect_config_service/domain/models/todo.py"
    entity.write_text(
        f"""from pydantic import ConfigDict

from arclith.domain.models.entity import Entity


ALIAS_CONFIG = {{"alias_generator": str.upper}}


class Todo(Entity):
    model_config = {configuration}
    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="may contain an alias_generator"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_dynamic_model_config_factory(tmp_path: Path) -> None:
    project = _project(tmp_path, "dynamic-config-service")
    entity = project / "src/dynamic_config_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import ConfigDict

from arclith.domain.models.entity import Entity


def build_config():
    return ConfigDict(alias_generator=str.upper)


class Todo(Entity):
    model_config = build_config()
    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="may contain an alias_generator"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_conditional_model_config(tmp_path: Path) -> None:
    project = _project(tmp_path, "conditional-config-service")
    entity = project / "src/conditional_config_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import ConfigDict

from arclith.domain.models.entity import Entity

USE_CAMEL = True


class Todo(Entity):
    if USE_CAMEL:
        model_config = ConfigDict(alias_generator=str.upper)
    external_id: str
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="class control flow"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_unpacked_field_options(tmp_path: Path) -> None:
    project = _project(tmp_path, "unpacked-field-service")
    entity = project / "src/unpacked_field_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import Field

from arclith.domain.models.entity import Entity

OPTIONS = {"alias": "uuid"}


class Todo(Entity):
    external_id: str = Field(**OPTIONS)
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Field metadata.*cannot be resolved"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "mode",
    ("local", "imported", "qualified", "nested_qualified", "legacy"),
)
def test_crud_blueprint_rejects_pydantic_metadata_in_type_aliases(
    tmp_path: Path,
    mode: str,
) -> None:
    project = _project(tmp_path, "alias-metadata-service")
    models = project / "src/alias_metadata_service/domain/models"
    alias_source = """from typing import Annotated

from pydantic import Field

type HiddenCode = Annotated[str, Field(exclude=True)]
"""
    if mode == "legacy":
        entity_source = """from typing import Annotated, TypeAlias as TA

from pydantic import Field

from arclith.domain.models.entity import Entity

HiddenCode: TA = Annotated[str, Field(exclude=True)]


class Todo(Entity):
    code: HiddenCode
"""
    elif mode in {"imported", "qualified", "nested_qualified"}:
        if mode == "nested_qualified":
            type_package = models / "product_types"
            type_package.mkdir()
            (type_package / "__init__.py").write_text("", encoding="utf-8")
            (type_package / "aliases.py").write_text(
                alias_source,
                encoding="utf-8",
            )
            entity_source = """from .product_types import aliases as pt

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: pt.HiddenCode
"""
        else:
            (models / "product_types.py").write_text(alias_source, encoding="utf-8")
            entity_source = (
                """from .product_types import HiddenCode

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: HiddenCode
"""
                if mode == "imported"
                else """from . import product_types as pt

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: pt.HiddenCode
"""
            )
    else:
        entity_source = f"""{alias_source}
from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: HiddenCode
"""
    (models / "todo.py").write_text(entity_source, encoding="utf-8")

    with pytest.raises(ValueError, match="Type alias.*contains Pydantic Field"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_type_alias_reexported_by_package(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "package-alias-service")
    models = project / "src/package_alias_service/domain/models"
    type_package = models / "product_types"
    type_package.mkdir()
    (type_package / "__init__.py").write_text(
        "from .aliases import HiddenCode\n",
        encoding="utf-8",
    )
    (type_package / "aliases.py").write_text(
        """from typing import Annotated

from pydantic import Field

type HiddenCode = Annotated[str, Field(exclude=True)]
""",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from .product_types import HiddenCode

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: HiddenCode
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Type alias.*contains Pydantic Field"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    ("declaration", "field"),
    (
        ("SECRET = Field(exclude=True)", "code: str = SECRET"),
        ("SECRET = Field(exclude=True)", "code: Annotated[str, SECRET]"),
        (
            "SECRET = Field(exclude=True)\ntype HiddenCode = Annotated[str, SECRET]",
            "code: HiddenCode",
        ),
        (
            "def hidden_field():\n    return Field(exclude=True)",
            "code: str = hidden_field()",
        ),
    ),
)
def test_crud_blueprint_rejects_indirect_pydantic_field_metadata(
    tmp_path: Path,
    declaration: str,
    field: str,
) -> None:
    project = _project(tmp_path, "indirect-field-service")
    entity = project / "src/indirect_field_service/domain/models/todo.py"
    entity.write_text(
        f"""from typing import Annotated

from pydantic import Field

from arclith.domain.models.entity import Entity

{declaration}


class Todo(Entity):
    {field}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="(Indirect Pydantic Field metadata|Type alias.*contains Pydantic Field)",
    ):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_pydantic_metadata_through_local_alias_chain(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "chained-alias-field-service")
    entity = project / "src/chained_alias_field_service/domain/models/todo.py"
    entity.write_text(
        """from typing import Annotated

from pydantic import Field

from arclith.domain.models.entity import Entity

Hidden = Annotated[str, Field(exclude=True)]
Public = Hidden


class Todo(Entity):
    code: Public
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Type alias.*contains Pydantic Field"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    ("declaration", "default"),
    (
        ("import shared_contracts", "shared_contracts.DEFAULT"),
        ("from pydantic import Field\n\nSECRET = Field(exclude=True)", "SECRET"),
    ),
)
def test_crud_blueprint_rejects_indirect_metadata_inside_direct_field(
    tmp_path: Path,
    declaration: str,
    default: str,
) -> None:
    project = _project(tmp_path, "nested-direct-field-service")
    entity = project / "src/nested_direct_field_service/domain/models/todo.py"
    entity.write_text(
        f"""{declaration}
from pydantic import Field

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: str = Field(default={default})
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_helper_with_local_import(tmp_path: Path) -> None:
    project = _project(tmp_path, "local-import-field-service")
    entity = project / "src/local_import_field_service/domain/models/todo.py"
    entity.write_text(
        """from arclith.domain.models.entity import Entity


def hidden_field():
    from pydantic import Field

    return Field(exclude=True)


class Todo(Entity):
    code: str = hidden_field()
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_resolves_local_pydantic_constructor_alias(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "aliased-constructor-field-service")
    entity = project / "src/aliased_constructor_field_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import Field as PydanticField

from arclith.domain.models.entity import Entity

Field = PydanticField


class Todo(Entity):
    code: str = Field(exclude=True)
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

    create_source = (
        project
        / "src/aliased_constructor_field_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    assert "exclude=True" not in create_source


def test_crud_blueprint_rejects_nested_field_info_in_direct_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "nested-annotated-field-service")
    entity = project / "src/nested_annotated_field_service/domain/models/todo.py"
    entity.write_text(
        """from typing import Annotated

from pydantic import Field
from pydantic.fields import FieldInfo

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: Annotated[str, Field(default=FieldInfo(exclude=True))]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    ("import_source", "field"),
    (
        ("from .field_metadata import SECRET", "code: str = SECRET"),
        ("from . import field_metadata as fm", "code: Annotated[str, fm.SECRET]"),
        (
            "from . import field_metadata as fm",
            "code: str = fm.Metadata.SECRET",
        ),
        ("from .field_metadata import Metadata", "code: str = Metadata.SECRET"),
    ),
)
def test_crud_blueprint_rejects_imported_indirect_field_metadata(
    tmp_path: Path,
    import_source: str,
    field: str,
) -> None:
    project = _project(tmp_path, "imported-field-service")
    models = project / "src/imported_field_service/domain/models"
    (models / "field_metadata.py").write_text(
        """from pydantic import Field

SECRET = Field(exclude=True)


class Metadata:
    SECRET = Field(exclude=True)
""",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        f"""from typing import Annotated

{import_source}

from arclith.domain.models.entity import Entity


class Todo(Entity):
    {field}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    ("import_source", "metadata"),
    (
        ("from pydantic.fields import FieldInfo", "FieldInfo(alias='uuid')"),
        ("import pydantic.fields", "pydantic.fields.FieldInfo(exclude=True)"),
        ("from pydantic import fields as pf", "pf.FieldInfo(exclude=True)"),
    ),
)
def test_crud_blueprint_rejects_direct_field_info_metadata(
    tmp_path: Path,
    import_source: str,
    metadata: str,
) -> None:
    project = _project(tmp_path, "field-info-service")
    entity = project / "src/field_info_service/domain/models/todo.py"
    entity.write_text(
        f"""from typing import Annotated

{import_source}

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: Annotated[str, {metadata}]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_reexported_field_info_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "reexported-field-info-service")
    models = project / "src/reexported_field_info_service/domain/models"
    (models / "field_metadata.py").write_text(
        """from pydantic.fields import FieldInfo

SECRET = FieldInfo(exclude=True)
""",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from typing import Annotated

from .field_metadata import SECRET

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: Annotated[str, SECRET]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_field_metadata_reexported_by_package(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "package-field-info-service")
    models = project / "src/package_field_info_service/domain/models"
    metadata_package = models / "field_metadata"
    metadata_package.mkdir()
    (metadata_package / "__init__.py").write_text(
        "from .definitions import SECRET\n",
        encoding="utf-8",
    )
    (metadata_package / "definitions.py").write_text(
        "from pydantic import Field\n\nSECRET = Field(exclude=True)\n",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from typing import Annotated

from .field_metadata import SECRET

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: Annotated[str, SECRET]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "field",
    (
        "code: Annotated[str, SECRET]",
        "code: str = SECRET",
    ),
)
def test_crud_blueprint_rejects_external_metadata_reexported_by_package(
    tmp_path: Path,
    field: str,
) -> None:
    project = _project(tmp_path, "external-package-field-service")
    models = project / "src/external_package_field_service/domain/models"
    metadata_package = models / "field_metadata"
    metadata_package.mkdir()
    (metadata_package / "__init__.py").write_text(
        "from shared_contracts import SECRET\n",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        f"""from typing import Annotated

from .field_metadata import SECRET

from arclith.domain.models.entity import Entity


class Todo(Entity):
    {field}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_uninspectable_external_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "external-field-info-service")
    entity = project / "src/external_field_info_service/domain/models/todo.py"
    entity.write_text(
        """from typing import Annotated

from shared_contracts import SECRET

from arclith.domain.models.entity import Entity


class Todo(Entity):
    code: Annotated[str, SECRET]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


@pytest.mark.parametrize(
    "field",
    (
        "code: ExternalCode",
        "code: str = shared_contracts.SECRET",
    ),
)
def test_crud_blueprint_rejects_uninspectable_external_field_contracts(
    tmp_path: Path,
    field: str,
) -> None:
    project = _project(tmp_path, "external-contract-service")
    entity = project / "src/external_contract_service/domain/models/todo.py"
    entity.write_text(
        f"""import shared_contracts
from shared_contracts import ExternalCode

from arclith.domain.models.entity import Entity


class Todo(Entity):
    {field}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="(Imported annotation|Indirect Pydantic Field metadata)",
    ):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_rejects_uninspectable_type_checking_alias(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "external-guarded-alias-service")
    entity = project / "src/external_guarded_alias_service/domain/models/todo.py"
    entity.write_text(
        """from __future__ import annotations

from typing import TYPE_CHECKING

from arclith.domain.models.entity import Entity

if TYPE_CHECKING:
    from shared_contracts import ExternalCode


class Todo(Entity):
    code: ExternalCode
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Imported annotation"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_isolates_generated_support_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "support-name-service")
    models = project / "src/support_name_service/domain/models"
    (models / "support.py").write_text(
        """BaseModel = str
Field = int
_ArclithCrudBaseModel = str
_ArclithCrudField = int
_ArclithCrudUUID = float
_ArclithCrudABC = bool
_arclith_crud_abstractmethod = bytes
""",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from .support import (
    BaseModel,
    Field,
    _ArclithCrudABC,
    _ArclithCrudBaseModel,
    _ArclithCrudField,
    _ArclithCrudUUID,
    _arclith_crud_abstractmethod,
)

from arclith.domain.models.entity import Entity


class Todo(Entity):
    payload: BaseModel
    rank: Field
    preferred_base: _ArclithCrudBaseModel
    preferred_field: _ArclithCrudField
    preferred_uuid: _ArclithCrudUUID
    preferred_abc: _ArclithCrudABC
    preferred_decorator: _arclith_crud_abstractmethod
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
    monkeypatch.syspath_prepend(str(project / "src"))
    create_contract = importlib.import_module(
        "support_name_service.domain.ports.inbound.create_todo"
    )
    update_contract = importlib.import_module(
        "support_name_service.domain.ports.inbound.update_todo"
    )
    create_source = (
        project / "src/support_name_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    update_source = (
        project / "src/support_name_service/domain/ports/inbound/update_todo.py"
    ).read_text(encoding="utf-8")

    assert "BaseModel as _ArclithCrudBaseModel_" in create_source
    assert "ABC as _ArclithCrudABC_" in create_source
    assert "abstractmethod as _arclith_crud_abstractmethod_" in create_source
    assert "Field as _ArclithCrudField_" in update_source
    assert "UUID as _ArclithCrudUUID_" in update_source
    assert create_contract.CreateTodoCommand.model_fields["payload"].annotation is str
    assert create_contract.CreateTodoCommand.model_fields["rank"].annotation is int
    command = create_contract.CreateTodoCommand(
        payload="ok",
        rank=2,
        preferred_base="base",
        preferred_field=3,
        preferred_uuid=4.0,
        preferred_abc=True,
        preferred_decorator=b"decorator",
    )
    assert command.model_dump()["preferred_uuid"] == 4.0
    assert (
        update_contract.UpdateTodoCommand.model_fields["preferred_abc"].annotation
        is bool
    )

    for module in tuple(sys.modules):
        if module == "support_name_service" or module.startswith(
            "support_name_service."
        ):
            sys.modules.pop(module)


def test_module_imports_do_not_flatten_runtime_conditionals() -> None:
    tree = ast.parse(
        """import sys
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
"""
    )

    assert {ast.unparse(statement) for statement in module_imports(tree)} == {
        "import sys",
        "from typing import TYPE_CHECKING as TC",
        "from .product_types import Money",
    }
    shadowed = ast.parse(
        """TYPE_CHECKING = False
if TYPE_CHECKING:
    import unavailable_dependency
"""
    )
    assert module_imports(shadowed) == ()


def test_crud_blueprint_tracks_rebindings_and_positional_factory_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "binding-order-service")
    models = project / "src/binding_order_service/domain/models"
    (models / "field_support.py").write_text(
        """import pydantic

PydanticField = pydantic.Field
ProjectedField = PydanticField
""",
        encoding="utf-8",
    )
    (models / "custom_support.py").write_text(
        """def Field(*, default: str, alias: str) -> str:
    return default
""",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from decimal import Decimal
from typing import ClassVar

from pydantic import Field, Field as PydanticField

from arclith.domain.models.entity import Entity

Decimal = str
ClassVar = str
from .custom_support import Field
from .field_support import ProjectedField


class Todo(Entity):
    price: Decimal
    marker: ClassVar
    code: str = Field(default="custom", alias="uuid")
    projected: str = ProjectedField(exclude=True, min_length=2)
    generated: str = PydanticField(..., default_factory=lambda: "generated")
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "binding_order_service.domain.ports.inbound.create_todo"
    )
    source = (
        project / "src/binding_order_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    request = contract.CreateTodoCommand(
        price="12.00",
        marker="regular field",
        projected="OK",
    )

    assert set(contract.CreateTodoCommand.model_fields) == {
        "code",
        "generated",
        "marker",
        "price",
        "projected",
    }
    assert contract.CreateTodoCommand.model_fields["price"].annotation is str
    assert contract.CreateTodoCommand.model_fields["marker"].annotation is str
    assert request.code == "custom"
    assert "generated" not in request.model_fields_set
    assert "Field(default='custom', alias='uuid')" in source
    assert "exclude=True" not in source
    assert "Field(..., default=None)" not in source

    for module in tuple(sys.modules):
        if module == "binding_order_service" or module.startswith(
            "binding_order_service."
        ):
            sys.modules.pop(module)


def test_crud_blueprint_rejects_package_reexported_field_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "package-metadata-service")
    models = project / "src/package_metadata_service/domain/models"
    (models / "definitions.py").write_text(
        "from pydantic import Field\n\nSECRET = Field(exclude=True)\n",
        encoding="utf-8",
    )
    (models / "__init__.py").write_text(
        "from .definitions import SECRET\n",
        encoding="utf-8",
    )
    (models / "todo.py").write_text(
        """from typing import Annotated

from arclith.domain.models.entity import Entity

from . import SECRET


class Todo(Entity):
    code: Annotated[str, SECRET]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Indirect Pydantic Field metadata"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_uses_origins_at_the_entity_declaration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "declaration-origin-service")
    entity = project / "src/declaration_origin_service/domain/models/todo.py"
    entity.write_text(
        """from typing import ClassVar

from pydantic import Field

from arclith.domain.models.entity import Entity


class Todo(Entity):
    collection: ClassVar[str] = "todos"
    code: str = Field(exclude=True, min_length=2)


ClassVar = str
Field = lambda **kwargs: kwargs
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "declaration_origin_service.domain.ports.inbound.create_todo"
    )
    source = (
        project / "src/declaration_origin_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")

    assert set(contract.CreateTodoCommand.model_fields) == {"code"}
    assert "exclude=True" not in source
    with pytest.raises(ValueError):
        contract.CreateTodoCommand(code="x")
    assert contract.CreateTodoCommand(code="OK").code == "OK"

    for module in tuple(sys.modules):
        if module == "declaration_origin_service" or module.startswith(
            "declaration_origin_service."
        ):
            sys.modules.pop(module)


@pytest.mark.parametrize(
    "entity_field",
    (
        "code: SAFE",
        "code: Annotated[str, SECRET]",
    ),
)
def test_crud_blueprint_rejects_imports_rebinding_safe_local_names(
    tmp_path: Path,
    entity_field: str,
) -> None:
    project = _project(tmp_path, "rebound-external-service")
    entity = project / "src/rebound_external_service/domain/models/todo.py"
    entity.write_text(
        f"""from typing import Annotated

from arclith.domain.models.entity import Entity

SAFE = str
SECRET = "safe"
from shared_contracts import SAFE, SECRET


class Todo(Entity):
    {entity_field}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="(Imported annotation|Indirect Pydantic Field metadata)",
    ):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_crud_blueprint_resolves_isolated_deferred_field_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "deferred-metadata-service")
    entity = project / "src/deferred_metadata_service/domain/models/todo.py"
    entity.write_text(
        """from typing import Annotated as A, ClassVar

from pydantic import Field

from arclith.domain.models.entity import Entity


class Todo(Entity):
    MIN_LENGTH: ClassVar[int] = 2
    code: "A[str, Field(exclude=True, min_length=MIN_LENGTH)]"
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "deferred_metadata_service.domain.ports.inbound.create_todo"
    )
    source = (
        project / "src/deferred_metadata_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")

    assert any(
        isinstance(statement, ast.ImportFrom)
        and statement.module == "pydantic"
        and any(alias.name == "Field" for alias in statement.names)
        for statement in ast.parse(source).body
    )
    assert "Todo.MIN_LENGTH" in source
    assert "exclude=True" not in source
    with pytest.raises(ValueError):
        contract.CreateTodoCommand(code="x")
    assert contract.CreateTodoCommand(code="OK").code == "OK"

    for module in tuple(sys.modules):
        if module == "deferred_metadata_service" or module.startswith(
            "deferred_metadata_service."
        ):
            sys.modules.pop(module)


@pytest.mark.parametrize(
    "declaration",
    (
        """class Todo(Entity):
    type Hidden = Annotated[str, Field(exclude=True)]
    code: Hidden
""",
        """Hidden = Public = Annotated[str, Field(exclude=True)]


class Todo(Entity):
    code: Hidden
""",
        """def hidden_field():
    F = Field
    return F(exclude=True)


class Todo(Entity):
    code: str = hidden_field()
""",
        """def build_metadata():
    F = Field
    return Annotated[str, F(exclude=True)]


type Hidden = build_metadata()


class Todo(Entity):
    code: Hidden
""",
    ),
)
def test_crud_blueprint_rejects_unprovable_local_metadata_forms(
    tmp_path: Path,
    declaration: str,
) -> None:
    project = _project(tmp_path, "review-edge-service")
    entity = project / "src/review_edge_service/domain/models/todo.py"
    entity.write_text(
        f"""from typing import Annotated

from pydantic import Field

from arclith.domain.models.entity import Entity


{declaration}""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="(Type alias.*Pydantic Field|Indirect Pydantic Field metadata)",
    ):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


def test_pep_695_rebinding_of_typing_marker_remains_a_business_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "typing-rebind-service")
    entity = project / "src/typing_rebind_service/domain/models/todo.py"
    entity.write_text(
        """from typing import ClassVar

from arclith.domain.models.entity import Entity

type ClassVar = str


class Todo(Entity):
    code: ClassVar
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "typing_rebind_service.domain.ports.inbound.create_todo"
    )

    assert set(contract.CreateTodoCommand.model_fields) == {"code"}
    assert contract.CreateTodoCommand(code="kept").code == "kept"

    for module in tuple(sys.modules):
        if module == "typing_rebind_service" or module.startswith(
            "typing_rebind_service."
        ):
            sys.modules.pop(module)


def test_nested_strings_in_deferred_annotated_metadata_remain_opaque(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "opaque-metadata-service")
    entity = project / "src/opaque_metadata_service/domain/models/todo.py"
    entity.write_text(
        """from typing import Annotated, ClassVar

from arclith.domain.models.entity import Entity


class Todo(Entity):
    MIN_LENGTH: ClassVar[int] = 2
    code: "Annotated[str, ('MIN_LENGTH',), ('Field(exclude=True)',)]"
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "opaque_metadata_service.domain.ports.inbound.create_todo"
    )
    source = (
        project / "src/opaque_metadata_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")
    field = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "code"
    )

    assert isinstance(field.annotation, ast.Constant)
    assert "'MIN_LENGTH'" in field.annotation.value
    assert "'Field(exclude=True)'" in field.annotation.value
    assert "Todo.MIN_LENGTH" not in field.annotation.value
    assert contract.CreateTodoCommand(code="opaque").code == "opaque"

    for module in tuple(sys.modules):
        if module == "opaque_metadata_service" or module.startswith(
            "opaque_metadata_service."
        ):
            sys.modules.pop(module)


def test_type_checking_typing_alias_sanitizes_deferred_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "guarded-typing-service")
    entity = project / "src/guarded_typing_service/domain/models/todo.py"
    entity.write_text(
        """from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from arclith.domain.models.entity import Entity

if TYPE_CHECKING:
    from typing import Annotated as A


class Todo(Entity):
    code: "A[str, Field(exclude=True, min_length=2)]"
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
    source = (
        project / "src/guarded_typing_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")

    assert "from typing import Annotated as A" in source
    assert "exclude=True" not in source
    assert "min_length=2" in source


def test_entity_literal_default_is_snapshotted_before_a_later_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "default-snapshot-service")
    entity = project / "src/default_snapshot_service/domain/models/todo.py"
    entity.write_text(
        """from arclith.domain.models.entity import Entity

DEFAULT = "old"


class Todo(Entity):
    code: str = DEFAULT


DEFAULT = "new"
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "default_snapshot_service.domain.ports.inbound.create_todo"
    )
    source = (
        project / "src/default_snapshot_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")

    assert "DEFAULT = 'old'" in source
    assert contract.CreateTodoCommand().code == "old"

    for module in tuple(sys.modules):
        if module == "default_snapshot_service" or module.startswith(
            "default_snapshot_service."
        ):
            sys.modules.pop(module)


def test_deferred_literal_member_imports_its_runtime_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "literal-member-service")
    entity = project / "src/literal_member_service/domain/models/todo.py"
    entity.write_text(
        """from enum import Enum
from typing import Literal

from arclith.domain.models.entity import Entity


class Status(str, Enum):
    ACTIVE = "active"


class Todo(Entity):
    status: "Literal[Status.ACTIVE]"
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "literal_member_service.domain.ports.inbound.create_todo"
    )
    entity_module = importlib.import_module("literal_member_service.domain.models.todo")
    source = (
        project / "src/literal_member_service/domain/ports/inbound/create_todo.py"
    ).read_text(encoding="utf-8")

    assert "Status" in source
    assert (
        contract.CreateTodoCommand(status=entity_module.Status.ACTIVE).status
        is entity_module.Status.ACTIVE
    )

    for module in tuple(sys.modules):
        if module == "literal_member_service" or module.startswith(
            "literal_member_service."
        ):
            sys.modules.pop(module)


def test_standard_library_new_type_alias_remains_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "new-type-service")
    entity = project / "src/new_type_service/domain/models/todo.py"
    entity.write_text(
        """from typing import NewType

from arclith.domain.models.entity import Entity

UserId = NewType("UserId", int)


class Todo(Entity):
    user_id: UserId
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
    monkeypatch.syspath_prepend(str(project / "src"))
    contract = importlib.import_module(
        "new_type_service.domain.ports.inbound.create_todo"
    )

    assert contract.CreateTodoCommand(user_id=7).user_id == 7

    for module in tuple(sys.modules):
        if module == "new_type_service" or module.startswith("new_type_service."):
            sys.modules.pop(module)


def test_crud_blueprint_rejects_import_collision_with_generated_contract(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "contract-collision-service")
    entity = project / "src/contract_collision_service/domain/models/todo.py"
    entity.write_text(
        """from pydantic import BaseModel

from arclith.domain.models.entity import Entity


class CreateTodoCommand(BaseModel):
    value: str


class Todo(Entity):
    payload: CreateTodoCommand
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="collide with generated CRUD"):
        add_application_blueprint_cmd(
            project_dir=project,
            blueprint_name="crud",
            entity_name="Todo",
            feature_name="todo",
            dry_run=False,
        )


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
