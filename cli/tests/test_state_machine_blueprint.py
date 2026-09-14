from __future__ import annotations

import json
import inspect
import os
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from arclith_cli.application_blueprint_recipe import (
    replay_add_entity_step,
    validate_application_recipe_metadata,
)
from arclith_cli.application_blueprints import (
    application_blueprint_digest,
    application_parameters_digest,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    apply_application_blueprint,
    plan_application_blueprint,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.feature_manifest import FeatureManifest, load_feature_manifest
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe
from arclith_cli.recipe_models import RecipeError, save_recipe
from arclith_cli.state_machine_spec import StateMachineSpec, load_state_machine_spec


runner = CliRunner()


def _parameters() -> dict[str, object]:
    return {
        "state_field": "status",
        "initial_state": "draft",
        "states": ["draft", "submitted", "approved", "rejected"],
        "transitions": [
            {"name": "submit", "from": ["draft"], "to": "submitted"},
            {"name": "approve", "from": ["submitted"], "to": "approved"},
            {"name": "reject", "from": ["submitted"], "to": "rejected"},
        ],
    }


def _spec_document(parameters: dict[str, object] | None = None) -> dict[str, object]:
    return {"version": 1, **(parameters or _parameters())}


def _parameterized_recipe_args() -> dict[str, object]:
    blueprint = get_application_blueprint("state-machine")
    parameters = StateMachineSpec.from_dict(_spec_document()).to_parameters()
    return {
        "entity": "Invoice",
        "profile": blueprint.name,
        "parameters": parameters,
        "template_digest": application_blueprint_digest(blueprint),
        "parameters_digest": application_parameters_digest(blueprint, parameters),
    }


def _project(tmp_path: Path, name: str = "invoice-service") -> Path:
    return init_project_cmd(project_name=name, directory=tmp_path)


def _write_spec(
    project: Path,
    parameters: dict[str, object] | None = None,
    *,
    filename: str = "invoice-lifecycle.yaml",
) -> Path:
    path = project / filename
    path.write_text(
        yaml.safe_dump(_spec_document(parameters), sort_keys=False),
        encoding="utf-8",
    )
    return path


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    arguments: list[str],
):
    monkeypatch.chdir(project)
    return runner.invoke(app, arguments)


def _stateful_entity(project: Path) -> Path:
    entity = add_entity_cmd(project_dir=project, entity_name="Invoice")
    entity.write_text(
        "from collections.abc import Mapping\n"
        "from typing import Any, Literal, Self\n\n"
        "from pydantic import ConfigDict, Field\n\n"
        "from arclith.domain.models.entity import Entity\n\n\n"
        "class Invoice(Entity):\n"
        "    model_config = ConfigDict(validate_assignment=True)\n"
        '    status: Literal["draft", "submitted", "approved", "rejected"] = '
        'Field(default="draft", frozen=True)\n\n'
        "    def model_copy(\n"
        "        self,\n"
        "        *,\n"
        "        update: Mapping[str, Any] | None = None,\n"
        "        deep: bool = False,\n"
        "    ) -> Self:\n"
        '        if update is not None and "status" in update:\n'
        '            raise ValueError("status changes must use the lifecycle")\n'
        "        return super().model_copy(update=update, deep=deep)\n\n"
        "    def _copy_with_status(self, target: str) -> Self:\n"
        '        return super().model_copy(update={"status": target})\n',
        encoding="utf-8",
    )
    return entity


def _local_state_enum(extra_body: str = "") -> str:
    lines = [
        "class InvoiceStatus(StrEnum):",
        '    DRAFT = "draft"',
        '    SUBMITTED = "submitted"',
        '    APPROVED = "approved"',
        '    REJECTED = "rejected"',
    ]
    if extra_body:
        lines.extend(extra_body.rstrip("\n").splitlines())
    return "\n".join(lines) + "\n\n\n"


def test_state_machine_is_discoverable_in_text_and_json_catalogues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)

    text_result = _invoke(monkeypatch, project, ["blueprints"])
    json_result = _invoke(monkeypatch, project, ["blueprints", "--json"])

    blueprint = get_application_blueprint("state-machine")
    assert blueprint.parameterized is True
    assert blueprint.operations == ()
    assert text_result.exit_code == 0, text_result.output
    assert "state-machine" in text_result.output
    entry = next(
        item
        for item in json.loads(json_result.output)
        if item["name"] == "state-machine"
    )
    assert entry["operations"] == []
    assert entry["parameterized"] is True
    assert "spec" in entry["description"]


@pytest.mark.parametrize(
    ("blueprint_name", "legacy_digest"),
    [
        (
            "crud",
            "sha256:768eabfa1af1d63c6c95d4f9abff4bdd44bd4bd2ccf2c7527694f0847f3fd028",
        ),
        (
            "append-only",
            "sha256:b4e82cdeee46b04a55563ba8160f5b7324ade25c8abf06dbff2968f7fd04e4b3",
        ),
    ],
)
def test_non_parameterized_blueprint_digests_remain_recipe_compatible(
    blueprint_name: str,
    legacy_digest: str,
) -> None:
    assert application_blueprint_digest(get_application_blueprint(blueprint_name)) == (
        legacy_digest
    )


def test_spec_is_canonical_and_digest_is_order_independent() -> None:
    first = StateMachineSpec.from_dict(_spec_document())
    reordered = StateMachineSpec.from_dict(
        {
            "version": 1,
            "state_field": "status",
            "initial_state": "draft",
            "states": ["rejected", "approved", "submitted", "draft"],
            "transitions": [
                {"name": "reject", "from": ["submitted"], "to": "rejected"},
                {"name": "submit", "from": ["draft"], "to": "submitted"},
                {"name": "approve", "from": ["submitted"], "to": "approved"},
            ],
        }
    )

    assert first == reordered
    assert first.operations == ("approve", "reject", "submit")
    assert first.digest() == reordered.digest()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first.digest())


def test_template_digest_covers_the_generated_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arclith_cli import state_machine_entity

    blueprint = get_application_blueprint("state-machine")
    before = application_blueprint_digest(blueprint)
    monkeypatch.setattr(
        state_machine_entity,
        "render_state_machine_entity",
        lambda *_args: "# changed entity template\n",
    )

    assert application_blueprint_digest(blueprint) != before


def test_template_digest_versions_existing_entity_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arclith_cli import state_machine_entity

    blueprint = get_application_blueprint("state-machine")
    before = application_blueprint_digest(blueprint)
    monkeypatch.setattr(
        state_machine_entity,
        "STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION",
        state_machine_entity.STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION + 1,
    )

    assert application_blueprint_digest(blueprint) != before


def test_template_digest_includes_the_complete_renderer_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arclith_cli import application_blueprints

    blueprint = get_application_blueprint("state-machine")
    before = application_blueprint_digest(blueprint)
    monkeypatch.setattr(
        application_blueprints,
        "_state_machine_renderer_contract_digest",
        lambda: "sha256:" + "0" * 64,
    )

    assert application_blueprint_digest(blueprint) != before


@pytest.mark.parametrize(
    "module_name",
    [
        "application_blueprints",
        "import_origins",
        "module_bindings",
        "state_machine_spec",
        "state_machine_contract",
        "state_machine_types",
    ],
)
def test_template_digest_includes_every_state_machine_contract_module(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    from arclith_cli import (
        application_blueprints,
        import_origins,
        module_bindings,
        state_machine_contract,
        state_machine_spec,
        state_machine_types,
    )

    blueprint = get_application_blueprint("state-machine")
    before = application_blueprint_digest(blueprint)
    original_getsource = inspect.getsource
    contract_module = {
        "application_blueprints": application_blueprints,
        "import_origins": import_origins,
        "module_bindings": module_bindings,
        "state_machine_contract": state_machine_contract,
        "state_machine_spec": state_machine_spec,
        "state_machine_types": state_machine_types,
    }[module_name]

    def changed_source(subject: object) -> str:
        source = original_getsource(subject)
        if subject is contract_module:
            return source + "\n# changed state-machine contract\n"
        return source

    monkeypatch.setattr(inspect, "getsource", changed_source)

    assert application_blueprint_digest(blueprint) != before


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {**_spec_document(), "initial_state": "missing"},
            "initial_state must be declared",
        ),
        (
            {
                **_spec_document(),
                "transitions": [
                    {"name": "submit", "from": ["missing"], "to": "submitted"}
                ],
            },
            "unknown source",
        ),
        (
            {
                **_spec_document(),
                "transitions": [{"name": "submit", "from": ["draft"], "to": "missing"}],
            },
            "unknown target",
        ),
        (
            {
                **_spec_document(),
                "states": ["draft", "submitted"],
                "transitions": [
                    {"name": "submit", "from": ["draft"], "to": "submitted"},
                    {"name": "submit", "from": ["submitted"], "to": "draft"},
                ],
            },
            "transition names must be unique",
        ),
        (
            {
                **_spec_document(),
                "states": ["draft", "submitted", "orphan"],
                "transitions": [
                    {"name": "submit", "from": ["draft"], "to": "submitted"}
                ],
            },
            "unreachable: orphan",
        ),
        ({**_spec_document(), "state_field": "version"}, "reserved by Entity"),
        ({**_spec_document(), "state_field": "coerce_uuid"}, "reserved by Entity"),
        ({**_spec_document(), "state_field": "model_copy"}, "reserved by Entity"),
        ({**_spec_document(), "state_field": "model_dump"}, "reserved by Entity"),
        ({**_spec_document(), "state_field": "class"}, "public Python identifier"),
        (
            {
                **_spec_document(),
                "initial_state": "draft",
                "states": ["draft", "DRAFT"],
                "transitions": [{"name": "promote", "from": ["draft"], "to": "DRAFT"}],
            },
            "unique generated enum member names",
        ),
        (
            {
                **_spec_document(),
                "states": ["draft", "sent"],
                "transitions": [
                    {"name": "send_email", "from": ["draft"], "to": "sent"},
                    {"name": "send__email", "from": ["draft"], "to": "sent"},
                ],
            },
            "unique generated class names",
        ),
    ],
)
def test_spec_rejects_invalid_invariants(
    document: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        StateMachineSpec.from_dict(document)


def test_spec_read_failures_are_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = tmp_path / "state-machine.yaml"
    spec_path.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="Unable to read state-machine spec"):
        load_state_machine_spec(spec_path)

    spec_path.write_text("version: 1\n", encoding="utf-8")

    def fail_read(_path: Path, *, encoding: str | None = None) -> str:
        raise OSError(f"unreadable with {encoding}")

    monkeypatch.setattr(Path, "read_text", fail_read)
    with pytest.raises(ValueError, match="Unable to read state-machine spec"):
        load_state_machine_spec(spec_path)


def test_profile_generates_typed_layers_and_parameterized_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    spec_path = _write_spec(project)

    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    package = project / "src/invoice_service"
    entity = (package / "domain/models/invoice.py").read_text(encoding="utf-8")
    service = (package / "domain/services/invoice.py").read_text(encoding="utf-8")
    store = (package / "domain/ports/outbound/invoice.py").read_text(encoding="utf-8")
    manifest = load_feature_manifest(project / ".arclith/features/invoice.yaml")

    assert "status: InvoiceState = Field(" in entity
    assert "frozen=True" in entity
    assert "def submit(" in service
    assert 'transition("' not in service
    assert "compare_and_swap" in store
    assert manifest.version == 2
    assert (
        manifest.parameters
        == StateMachineSpec.from_dict(_spec_document()).to_parameters()
    )
    assert manifest.operations == ("approve", "reject", "submit")
    assert manifest.digests is not None
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.digests.template)
    assert (
        manifest.digests.parameters
        == StateMachineSpec.from_dict(_spec_document()).digest()
    )
    for operation in manifest.operations:
        assert (package / f"domain/ports/inbound/{operation}_invoice.py").is_file()
        assert (package / f"application/use_cases/{operation}_invoice.py").is_file()
    assert (project / "tests/domain/test_invoice.py").is_file()
    assert (project / "tests/application/test_invoice_use_cases.py").is_file()
    assert (project / "docs/blueprints/invoice-state-machine.md").is_file()
    assert not (package / "adapters/inbound/fastapi").exists()
    assert not (package / "adapters/inbound/fastmcp").exists()


def test_profile_handles_a_sparse_model_package_and_configurable_state_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "sparse-service")
    models = project / "src/sparse_service/domain/models"
    (models / "__init__.py").unlink()
    models.rmdir()
    parameters = {**_parameters(), "state_field": "phase"}
    spec_path = _write_spec(project, parameters)

    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (models / "__init__.py").read_bytes() == b""
    assert (models / "invoice.py").is_file()
    assert (models / "invoice_lifecycle_state.py").is_file()
    domain_tests = (project / "tests/domain/test_invoice.py").read_text(
        encoding="utf-8"
    )
    assert "def test_invoice_phase_rejects_arbitrary_assignment" in domain_tests


def test_all_states_allowed_generates_lint_clean_application_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "always-allowed-service")
    parameters = {
        "state_field": "status",
        "initial_state": "draft",
        "states": ["draft", "submitted"],
        "transitions": [
            {
                "name": "synchronize",
                "from": ["draft", "submitted"],
                "to": "submitted",
            }
        ],
    }
    spec_path = _write_spec(project, parameters)
    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )
    assert result.exit_code == 0, result.output

    application_test = project / "tests/application/test_invoice_use_cases.py"
    assert "TransitionNotAllowedError" not in application_test.read_text(
        encoding="utf-8"
    )
    lint = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_manifest_v2_rejects_parameter_digest_drift_and_non_json_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    spec_path = _write_spec(project)
    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest_path = project / ".arclith/features/invoice.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["parameters"]["initial_state"] = "submitted"
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match canonical parameters"):
        load_feature_manifest(manifest_path)

    raw["parameters"]["created"] = "2026-09-14"
    rendered = yaml.safe_dump(raw, sort_keys=False).replace(
        "created: '2026-09-14'", "created: 2026-09-14"
    )
    manifest_path.write_text(rendered, encoding="utf-8")
    with pytest.raises(ValueError, match="JSON/YAML-safe"):
        load_feature_manifest(manifest_path)


@pytest.mark.parametrize("missing_key", ["parameters", "digests"])
def test_manifest_v2_normalizes_missing_parameterized_fields(
    missing_key: str,
) -> None:
    spec = StateMachineSpec.from_dict(_spec_document())
    raw: dict[str, object] = {
        "version": 2,
        "feature": "invoice",
        "entity": {
            "name": "Invoice",
            "module": "invoice_service.domain.models.invoice",
        },
        "blueprint": {"name": "state-machine", "version": 1},
        "parameters": spec.to_parameters(),
        "digests": {
            "template": "sha256:" + "0" * 64,
            "parameters": spec.digest(),
        },
        "operations": list(spec.operations),
    }
    del raw[missing_key]

    with pytest.raises(ValueError, match="must contain exactly"):
        FeatureManifest.from_dict(raw)


def test_manifest_v2_rejects_recursive_yaml_parameters(tmp_path: Path) -> None:
    manifest_path = tmp_path / "recursive.yaml"
    digest = "sha256:" + "0" * 64
    manifest_path.write_text(
        "version: 2\n"
        "feature: invoice\n"
        "entity:\n"
        "  name: Invoice\n"
        "  module: invoice_service.domain.models.invoice\n"
        "blueprint:\n"
        "  name: state-machine\n"
        "  version: 1\n"
        "parameters: &parameters\n"
        "  self: *parameters\n"
        "digests:\n"
        f"  template: {digest}\n"
        f"  parameters: {digest}\n"
        "operations: [submit]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recursive containers"):
        load_feature_manifest(manifest_path)


def test_missing_or_unprotected_existing_state_field_is_rejected_without_writes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = add_entity_cmd(project_dir=project, entity_name="Invoice")
    before = entity.read_bytes()

    with pytest.raises(ValueError, match="must declare typed field 'status'"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )

    assert entity.read_bytes() == before
    assert not (project / ".arclith/features/invoice_lifecycle.yaml").exists()

    entity.write_text(
        "from typing import Literal\n"
        "from arclith.domain.models.entity import Entity\n\n"
        "class Invoice(Entity):\n"
        '    status: Literal["draft", "submitted", "approved", "rejected"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )

    entity.write_text(
        "from typing import Literal\n"
        "from pydantic import ConfigDict, Field\n"
        "from arclith.domain.models.entity import Entity\n\n"
        "class Invoice(Entity):\n"
        "    model_config = ConfigDict(validate_assignment=True)\n"
        '    status: Literal["draft", "submitted", "approved", "rejected"] = '
        'Field(default="draft", frozen=True)\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_compatible_entity_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    original = entity.read_bytes()
    spec_path = _write_spec(project)

    result = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--feature",
            "invoice_lifecycle",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert entity.read_bytes() == original
    assert (project / ".arclith/features/invoice_lifecycle.yaml").is_file()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from invoice_service.domain.models.invoice import Invoice; "
                "from invoice_service.domain.services.invoice_lifecycle import "
                "InvoiceLifecycle; changed = InvoiceLifecycle().submit(Invoice()); "
                "assert changed.status == 'submitted'; "
                "assert type(changed.status) is str"
            ),
        ],
        cwd=project,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_existing_enum_values_must_match_the_spec(tmp_path: Path) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import Enum as BaseEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        "class InvoiceStatus(BaseEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n\n\n'
        "StatusAlias = InvoiceStatus\n\n\n"
        "class Invoice(Entity):\n",
    )
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    entity.write_text(content.replace(literal, "StatusAlias"), encoding="utf-8")

    with pytest.raises(ValueError, match="must use its declared enum type"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )

    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    plan = plan_application_blueprint(
        project,
        blueprint_name="state-machine",
        entity_name="Invoice",
        feature_name="invoice_lifecycle",
        parameters=_parameters(),
    )
    apply_application_blueprint(plan)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from invoice_service.domain.models.invoice import Invoice, InvoiceStatus; "
                "from invoice_service.domain.services.invoice_lifecycle import "
                "InvoiceLifecycle; "
                "changed = InvoiceLifecycle().submit("
                "Invoice(status=InvoiceStatus.DRAFT)); "
                "assert changed.status is InvoiceStatus.SUBMITTED"
            ),
        ],
        cwd=project,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    entity.write_text(
        entity.read_text(encoding="utf-8").replace('    APPROVED = "approved"\n', ""),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Literal containing exactly"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "extra_body",
    [
        '    if True:\n        CANCELLED = "cancelled"\n',
        "".join(
            [
                '    try:\n        CANCELLED = "cancelled"\n',
                "    except Exception:\n        pass\n",
            ]
        ),
        '    match True:\n        case True:\n            CANCELLED = "cancelled"\n',
        '    _HIDDEN = "cancelled"\n',
        '    (CANCELLED := "cancelled")\n',
        "".join(
            [
                "    @member\n",
                "    def CANCELLED() -> str:\n",
                '        return "cancelled"\n',
            ]
        ),
        "".join(
            [
                "    def __new__(cls, value: str):\n",
                "        member = str.__new__(cls, value)\n",
                "        member._value_ = value.upper()\n",
                "        return member\n",
            ]
        ),
        "".join(
            [
                "    def __init__(self, value: str) -> None:\n",
                "        object.__setattr__(self, '_value_', value.upper())\n",
            ]
        ),
        "".join(
            [
                "    def mutate(self) -> None:\n",
                "        object.__setattr__(self, '_value_', 'cancelled')\n",
            ]
        ),
        '    DRAFT = "draft"\n',
    ],
)
def test_existing_enum_rejects_uninspectable_runtime_members(
    tmp_path: Path,
    extra_body: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum, member\n",
    ).replace(
        "class Invoice(Entity):\n",
        _local_state_enum(extra_body) + "class Invoice(Entity):\n",
    )
    entity.write_text(
        content.replace(literal, "InvoiceStatus").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_enum_rejects_a_class_decorator(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    decorated_enum = _local_state_enum().replace(
        "class InvoiceStatus(StrEnum):",
        "@replace_enum\nclass InvoiceStatus(StrEnum):",
    )
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        decorated_enum + "class Invoice(Entity):\n",
    )
    entity.write_text(
        content.replace(literal, "InvoiceStatus").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_enum_rejects_a_custom_mixin(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    mixed_enum = _local_state_enum().replace(
        "class InvoiceStatus(StrEnum):",
        "class InvoiceStatus(CustomMixin, StrEnum):",
    )
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        "class CustomMixin:\n"
        "    def __new__(cls, value: str):\n"
        "        return str.__new__(cls, value.upper())\n\n\n"
        + mixed_enum
        + "class Invoice(Entity):\n",
    )
    entity.write_text(
        content.replace(literal, "InvoiceStatus").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_enum_rejects_use_enum_values(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        "class InvoiceStatus(StrEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n\n\n'
        "class Invoice(Entity):\n",
    )
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    entity.write_text(
        content.replace(literal, "InvoiceStatus")
        .replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        )
        .replace(
            "ConfigDict(validate_assignment=True)",
            "ConfigDict(validate_assignment=True, use_enum_values=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="use_enum_values disabled"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "replacement",
    [
        'Field(default="unknown", frozen=True)',
        'Field(default_factory=lambda: "draft", frozen=True)',
        "Field(frozen=True, **options)",
    ],
)
def test_existing_literal_requires_a_static_declared_default(
    tmp_path: Path,
    replacement: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            'Field(default="draft", frozen=True)',
            replacement,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="static default"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )

    assert not (project / ".arclith/features/invoice_lifecycle.yaml").exists()


def test_existing_imported_enum_alias_is_inspected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    status_module = entity.with_name("invoice_status.py")
    status_module.write_text(
        "from enum import StrEnum\n\n\n"
        "class Status(StrEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n',
        encoding="utf-8",
    )
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace(
            "from typing import Any, Literal, Self\n",
            "from typing import Any, Literal, Self\n\n"
            "from .invoice_status import Status as InvoiceStatus\n",
        )
        .replace(
            'Literal["draft", "submitted", "approved", "rejected"]',
            "InvoiceStatus",
        )
        .replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    plan_application_blueprint(
        project,
        blueprint_name="state-machine",
        entity_name="Invoice",
        feature_name="invoice_lifecycle",
        parameters=_parameters(),
    )


def test_existing_entity_rejects_type_checking_only_enum_import(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    status_module = entity.with_name("invoice_status.py")
    status_module.write_text(
        "from enum import StrEnum\n\n\n"
        "class InvoiceStatus(StrEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n',
        encoding="utf-8",
    )
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from typing import Any, Literal, Self\n",
        "from typing import Any, Self, TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from .invoice_status import InvoiceStatus\n",
    )
    entity.write_text(
        content.replace(literal, "InvoiceStatus").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_typing_literal_import_alias_is_inspected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace(
            "from typing import Any, Literal, Self",
            "from typing import Any, Literal as StateLiteral, Self",
        )
        .replace("Literal[", "StateLiteral["),
        encoding="utf-8",
    )

    plan_application_blueprint(
        project,
        blueprint_name="state-machine",
        entity_name="Invoice",
        feature_name="invoice_lifecycle",
        parameters=_parameters(),
    )


def test_existing_local_literal_alias_is_inspected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace(
            "class Invoice(Entity):\n",
            f"InvoiceStatus = {literal}\n\n\nclass Invoice(Entity):\n",
        )
        .replace(f"status: {literal}", "status: InvoiceStatus"),
        encoding="utf-8",
    )

    plan_application_blueprint(
        project,
        blueprint_name="state-machine",
        entity_name="Invoice",
        feature_name="invoice_lifecycle",
        parameters=_parameters(),
    )


def test_existing_literal_alias_must_be_declared_before_the_entity(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    content = entity.read_text(encoding="utf-8").replace(
        f"status: {literal}",
        "status: InvoiceStatus",
    )
    entity.write_text(
        content + f"\n\nInvoiceStatus = {literal}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_enum_must_be_declared_before_the_entity(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    content = entity.read_text(encoding="utf-8").replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    )
    content = content.replace(literal, "InvoiceStatus").replace(
        'Field(default="draft", frozen=True)',
        "Field(default=InvoiceStatus.DRAFT, frozen=True)",
    )
    entity.write_text(
        content + "\n\n" + _local_state_enum(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_rejects_a_shadowed_literal_helper(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "from typing import Any, Literal, Self",
            "from typing import Any, Self\n\nLiteral = str",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "binding",
    [
        "[(Literal := object()) for _ in (0,)]",
        "del Literal",
    ],
)
def test_existing_entity_rejects_dynamic_literal_rebinding(
    tmp_path: Path,
    binding: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "class Invoice(Entity):\n",
            f"{binding}\n\n\nclass Invoice(Entity):\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_rejects_enum_rebound_by_comprehension_walrus(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        _local_state_enum()
        + "[(InvoiceStatus := object()) for _ in (0,)]\n\n\n"
        + "class Invoice(Entity):\n",
    )
    entity.write_text(
        content.replace(literal, "InvoiceStatus").replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_rejects_a_project_local_enum_base(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    literal = 'Literal["draft", "submitted", "approved", "rejected"]'
    fake_enum = (
        "class Enum:\n"
        "    pass\n\n\n"
        "class InvoiceStatus(Enum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n\n\n'
    )
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace("class Invoice(Entity):\n", fake_enum + "class Invoice(Entity):\n")
        .replace(f"status: {literal}", "status: InvoiceStatus"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statically inspectable"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_conventional_state_module_is_preserved(tmp_path: Path) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    state_module = entity.with_name("invoice_state.py")
    state_module.write_text(
        "from enum import StrEnum\n\n\n"
        "class InvoiceState(StrEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n',
        encoding="utf-8",
    )
    original_state_module = state_module.read_bytes()
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace(
            "from typing import Any, Literal, Self\n",
            "from typing import Any, Self\n\nfrom .invoice_state import InvoiceState\n",
        )
        .replace(
            'Literal["draft", "submitted", "approved", "rejected"]',
            "InvoiceState",
        )
        .replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceState.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    plan = plan_application_blueprint(
        project,
        blueprint_name="state-machine",
        entity_name="Invoice",
        feature_name="invoice_lifecycle",
        parameters=_parameters(),
    )
    apply_application_blueprint(plan)

    assert state_module.read_bytes() == original_state_module
    generated_state = entity.with_name("invoice_lifecycle_state.py")
    assert generated_state.is_file()
    service = entity.parents[1] / "services" / "invoice_lifecycle.py"
    assert "domain.models.invoice_lifecycle_state import InvoiceState" in (
        service.read_text(encoding="utf-8")
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from invoice_service.domain.models.invoice import Invoice; "
                "from invoice_service.domain.models.invoice_state import InvoiceState; "
                "from invoice_service.domain.services.invoice_lifecycle import "
                "InvoiceLifecycle; changed = InvoiceLifecycle().submit("
                "Invoice(status=InvoiceState.DRAFT)); "
                "assert changed.status is InvoiceState.SUBMITTED"
            ),
        ],
        cwd=project,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_existing_entity_rejects_a_deceptive_state_copy_helper(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            '{"status": target}',
            '{"created_by": target}',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            '        if update is not None and "status" in update:\n',
            '        if "status" in update and update is not None:\n',
        ),
        (
            "from arclith.domain.models.entity import Entity\n",
            "from arclith.domain.models.entity import Entity\n\n"
            "super = lambda: object()\n",
        ),
        (
            '            raise ValueError("status changes must use the lifecycle")\n',
            '            raise ValueError("status changes must use the lifecycle") '
            "from (super := RuntimeError)\n",
        ),
        (
            '            raise ValueError("status changes must use the lifecycle")\n',
            '            raise RuntimeError("status changes must use the lifecycle")\n',
        ),
        (
            '            raise ValueError("status changes must use the lifecycle")\n',
            '            raise ValueError("status update rejected")\n',
        ),
    ],
)
def test_existing_entity_rejects_unsafe_public_copy_guards(
    tmp_path: Path,
    before: str,
    after: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize("method", ["model_copy", "_copy_with_status"])
def test_existing_entity_rejects_async_copy_helpers(
    tmp_path: Path,
    method: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            f"    def {method}(",
            f"    async def {method}(",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "        self,\n        *,\n",
            "        self,\n        required: object,\n        *,\n",
        ),
        (
            "    def _copy_with_status(self, target: str) -> Self:\n",
            "    def _copy_with_status(\n"
            "        self, target: str, required: object\n"
            "    ) -> Self:\n",
        ),
        (
            "    def _copy_with_status(self, target: str) -> Self:\n",
            "    @staticmethod\n"
            "    def _copy_with_status(self, target: str) -> Self:\n",
        ),
    ],
)
def test_existing_entity_rejects_incompatible_copy_helper_bindings(
    tmp_path: Path,
    before: str,
    after: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_rejects_reassigned_model_config(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8")
        .replace(
            "    model_config = ConfigDict(validate_assignment=True)\n",
            "    model_config = ConfigDict(frozen=True)\n"
            "    model_config = ConfigDict(validate_assignment=True)\n",
        )
        .replace(
            'Field(default="draft", frozen=True)',
            'Field(default="draft")',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "binding",
    [
        '    status = "draft"\n',
        '    if True:\n        status = "draft"\n',
        "".join(
            [
                '    try:\n        status = "draft"\n',
                "    except Exception:\n        pass\n",
            ]
        ),
        "".join(
            [
                "    try:\n        raise RuntimeError\n",
                "    except Exception as status:\n        pass\n",
            ]
        ),
        '    match True:\n        case True:\n            status = "draft"\n',
    ],
)
def test_existing_entity_rejects_additional_state_field_bindings(
    tmp_path: Path,
    binding: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8") + "\n" + binding,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly one class-scope binding"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "override",
    [
        "".join(
            [
                "    def __setattr__(self, name: str, value: object) -> None:\n",
                "        object.__setattr__(self, name, value)\n\n",
            ]
        ),
        "".join(
            [
                "    if True:\n",
                "        def __setattr__(self, name: str, value: object) -> None:\n",
                "            object.__setattr__(self, name, value)\n\n",
            ]
        ),
    ],
)
def test_existing_entity_rejects_class_scope_setattr_override(
    tmp_path: Path,
    override: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "    model_config = ConfigDict(validate_assignment=True)\n",
            override + "    model_config = ConfigDict(validate_assignment=True)\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "replacement",
    [
        "ConfigDict(validate_assignment=True, use_enum_values=USE_ENUM_VALUES)",
        "ConfigDict(validate_assignment=True, **CONFIG_OPTIONS)",
    ],
)
def test_existing_entity_rejects_dynamic_model_config(
    tmp_path: Path,
    replacement: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "ConfigDict(validate_assignment=True)",
            replacement,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_requires_real_pydantic_assignment_helpers(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "from pydantic import ConfigDict, Field",
            "from custom import ConfigDict, Field",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "relative_module",
    [
        "collections.py",
        "typing.py",
        "src/enum.py",
        "pydantic/__init__.py",
        "src/collections/__init__.py",
        "src/typing_extensions.py",
    ],
)
def test_existing_entity_rejects_shadowed_trusted_import_modules(
    tmp_path: Path,
    relative_module: str,
) -> None:
    project = _project(tmp_path)
    _stateful_entity(project)
    shadow = project / relative_module
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("# Project-owned import shadow.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="shadows trusted state contract modules"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "relative_module",
    [
        "collections.py",
        "typing.py",
        "src/enum.py",
        "pydantic/__init__.py",
        "src/collections/__init__.py",
        "src/typing_extensions.py",
    ],
)
def test_profile_rejects_shadowed_trusted_imports_before_creating_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_module: str,
) -> None:
    project = _project(tmp_path)
    spec_path = _write_spec(project)
    shadow = project / relative_module
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("# Project-owned import shadow.\n", encoding="utf-8")

    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 1
    assert "shadows trusted state contract modules" in result.output
    assert not (project / "src/invoice_service/domain/models/invoice.py").exists()
    assert not (project / ".arclith/features/invoice.yaml").exists()


@pytest.mark.parametrize("helper", ["ConfigDict", "Field"])
def test_existing_entity_rejects_shadowed_pydantic_helpers(
    tmp_path: Path,
    helper: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "from pydantic import ConfigDict, Field",
            f"from pydantic import ConfigDict, Field\n\n{helper} = dict",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must reject assignment"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "binding",
    [
        "if USE_CUSTOM:\n    Field = object\n",
        "for Literal in (str,):\n    pass\n",
        "try:\n    ConfigDict = dict\nexcept Exception:\n    pass\n",
    ],
)
def test_existing_entity_rejects_contract_helpers_rebound_by_module_control_flow(
    tmp_path: Path,
    binding: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "class Invoice(Entity):\n",
            f"{binding}\nclass Invoice(Entity):\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "binding",
    [
        "try:\n    raise RuntimeError\nexcept Exception as super:\n    pass\n",
        "match object():\n    case _ as super:\n        pass\n",
    ],
)
def test_existing_entity_rejects_string_stored_module_builtin_bindings(
    tmp_path: Path,
    binding: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "class Invoice(Entity):\n",
            f"{binding}\nclass Invoice(Entity):\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize(
    "binding",
    [
        (
            "    try:\n"
            "        raise RuntimeError\n"
            "    except Exception as model_copy:\n"
            "        pass\n"
        ),
        "    match object():\n        case _ as model_copy:\n            pass\n",
    ],
)
def test_existing_entity_rejects_string_stored_class_copy_bindings(
    tmp_path: Path,
    binding: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8") + "\n" + binding,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reject generic model_copy updates"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


@pytest.mark.parametrize("dependency", ["ConfigDict", "Field", "Literal"])
def test_existing_entity_rejects_class_scope_contract_shadowing(
    tmp_path: Path,
    dependency: str,
) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            "class Invoice(Entity):\n",
            f"class Invoice(Entity):\n    {dependency} = object\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="shadows state contract dependencies"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_existing_entity_rejects_class_scope_enum_shadowing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entity = _stateful_entity(project)
    content = entity.read_text(encoding="utf-8")
    content = content.replace(
        "from collections.abc import Mapping\n",
        "from collections.abc import Mapping\nfrom enum import StrEnum\n",
    ).replace(
        "class Invoice(Entity):\n",
        "class InvoiceStatus(StrEnum):\n"
        '    DRAFT = "draft"\n'
        '    SUBMITTED = "submitted"\n'
        '    APPROVED = "approved"\n'
        '    REJECTED = "rejected"\n\n\n'
        "class Invoice(Entity):\n"
        "    InvoiceStatus = str\n",
    )
    entity.write_text(
        content.replace(
            'Literal["draft", "submitted", "approved", "rejected"]',
            "InvoiceStatus",
        ).replace(
            'Field(default="draft", frozen=True)',
            "Field(default=InvoiceStatus.DRAFT, frozen=True)",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="shadows state contract dependencies"):
        plan_application_blueprint(
            project,
            blueprint_name="state-machine",
            entity_name="Invoice",
            feature_name="invoice_lifecycle",
            parameters=_parameters(),
        )


def test_generated_matrix_supports_existing_required_business_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _project(tmp_path, "required-field-service")
    entity = _stateful_entity(project)
    entity.write_text(
        entity.read_text(encoding="utf-8").replace(
            'Field(default="draft", frozen=True)\n\n',
            'Field(default="draft", frozen=True)\n    amount: int\n\n',
        ),
        encoding="utf-8",
    )
    entity.rename(entity.with_name("invoice_record.py"))
    spec_path = _write_spec(project)

    result = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--feature",
            "invoice_lifecycle",
            "--spec",
            str(spec_path),
        ],
    )
    assert result.exit_code == 0, result.output

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "tests/domain/test_invoice_lifecycle.py",
            "tests/application/test_invoice_lifecycle_use_cases.py",
            "-q",
        ],
        cwd=project,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_invalid_spec_and_dry_run_have_no_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    invalid = _write_spec(
        project,
        {**_parameters(), "initial_state": "missing"},
        filename="invalid.yaml",
    )
    before_invalid = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    invalid_result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(invalid),
        ],
    )
    assert invalid_result.exit_code == 1
    assert not (project / "src/invoice_service/domain/models/invoice.py").exists()
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before_invalid

    _stateful_entity(project)
    valid = _write_spec(project)
    before_dry_run = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    dry_run = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--spec",
            str(valid),
            "--dry-run",
        ],
    )
    assert dry_run.exit_code == 0, dry_run.output
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before_dry_run


def test_spec_drift_is_rejected_and_developer_files_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    _stateful_entity(project)
    original_spec = _write_spec(project)
    first = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--feature",
            "invoice_lifecycle",
            "--spec",
            str(original_spec),
        ],
    )
    assert first.exit_code == 0, first.output
    use_case = project / "src/invoice_service/application/use_cases/submit_invoice.py"
    use_case.write_text(
        use_case.read_text(encoding="utf-8") + "\n# project-owned rule\n",
        encoding="utf-8",
    )
    changed = {
        **_parameters(),
        "transitions": [
            *_parameters()["transitions"],  # type: ignore[misc]
            {"name": "reopen", "from": ["rejected"], "to": "draft"},
        ],
    }
    changed_spec = _write_spec(project, changed, filename="changed.yaml")

    replay = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--feature",
            "invoice_lifecycle",
            "--spec",
            str(changed_spec),
        ],
    )

    assert replay.exit_code == 1
    assert "different" in replay.output
    assert "canonical manifest" in replay.output
    assert use_case.read_text(encoding="utf-8").endswith("# project-owned rule\n")
    assert not (
        project / "src/invoice_service/application/use_cases/reopen_invoice.py"
    ).exists()


def test_profile_collision_is_atomic_and_recipe_replay_needs_no_spec_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision_project = _project(tmp_path, "collision-service")
    collision = (
        collision_project
        / "src/collision_service/application/use_cases/submit_invoice.py"
    )
    collision.write_text("# project-owned\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        replay_add_entity_step(
            collision_project,
            _parameterized_recipe_args(),
        )
    assert collision.read_text(encoding="utf-8") == "# project-owned\n"
    assert not (
        collision_project / "src/collision_service/domain/models/invoice.py"
    ).exists()

    project = _project(tmp_path, "recipe-service")
    spec_path = _write_spec(project)
    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )
    assert result.exit_code == 0, result.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    step = recipe.steps[-1]
    assert (
        step.args["parameters"]
        == StateMachineSpec.from_dict(_spec_document()).to_parameters()
    )
    assert "spec" not in step.args
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", step.args["parameters_digest"])

    drift_target = _project(tmp_path, "recipe-drift")
    drifted_parameters = dict(step.args["parameters"])
    drifted_parameters["state_field"] = "phase"
    with pytest.raises(ValueError, match="parameters digest drift"):
        replay_add_entity_step(
            drift_target,
            {**step.args, "parameters": drifted_parameters},
        )
    assert not (drift_target / "src/recipe_drift/domain/models/invoice.py").exists()

    spec_path.unlink()

    replay_target = _project(tmp_path, "recipe-replay")
    replay_recipe(recipe, recipe.steps, target_dir=replay_target, strict=True)
    replayed = load_feature_manifest(replay_target / ".arclith/features/invoice.yaml")
    assert replayed.parameters == step.args["parameters"]


@pytest.mark.parametrize("missing_digest", ["template_digest", "parameters_digest"])
def test_parameterized_recipe_requires_complete_digest_metadata_before_writes(
    tmp_path: Path,
    missing_digest: str,
) -> None:
    project = _project(tmp_path, f"missing-{missing_digest.replace('_', '-')}")
    args = _parameterized_recipe_args()
    del args[missing_digest]

    with pytest.raises(RecipeError, match="replay requires both"):
        replay_add_entity_step(project, args)

    validate_application_recipe_metadata("crud", {})
    assert not list(project.rglob("invoice.py"))


@pytest.mark.parametrize(
    "parameters",
    [None, {"state_field": "status"}],
)
def test_parameterized_recipe_normalizes_invalid_recorded_parameters(
    tmp_path: Path,
    parameters: dict[str, object] | None,
) -> None:
    project = _project(tmp_path, "invalid-parameters")
    args = _parameterized_recipe_args()
    if parameters is None:
        del args["parameters"]
    else:
        args["parameters"] = parameters

    with pytest.raises(RecipeError, match="invalid recorded parameters"):
        replay_add_entity_step(project, args)

    assert not list(project.rglob("invoice.py"))


def test_full_recipe_preflights_all_blueprint_metadata_before_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = runner.invoke(app, ["init", "preflight-source", "--dir", str(tmp_path)])
    assert created.exit_code == 0, created.output
    project = tmp_path / "preflight-source"
    spec_path = _write_spec(project)
    added = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )
    assert added.exit_code == 0, added.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    incomplete_step = replace(
        recipe.steps[-1],
        args={
            key: value
            for key, value in recipe.steps[-1].args.items()
            if key != "template_digest"
        },
    )
    incomplete_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], incomplete_step),
    )
    target = tmp_path / "preflight-target"

    with pytest.raises(RecipeError, match="replay requires both"):
        replay_recipe(
            incomplete_recipe,
            incomplete_recipe.steps,
            target_dir=target,
            strict=True,
        )

    assert not target.exists()

    save_recipe(incomplete_recipe, project / "incomplete.recipe.yaml")
    cli_result = runner.invoke(
        app,
        [
            "replay",
            str(project / "incomplete.recipe.yaml"),
            "--dir",
            str(target),
            "--strict",
        ],
    )
    assert cli_result.exit_code == 1
    assert "Recette CLI invalide" in cli_result.output
    assert "replay requires both" in " ".join(cli_result.output.split())
    assert not target.exists()

    malformed_step = replace(
        recipe.steps[-1],
        args={**recipe.steps[-1].args, "parameters": {"state_field": "status"}},
    )
    malformed_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], malformed_step),
    )
    save_recipe(malformed_recipe, project / "malformed.recipe.yaml")
    cli_result = runner.invoke(
        app,
        [
            "replay",
            str(project / "malformed.recipe.yaml"),
            "--dir",
            str(target),
            "--strict",
        ],
    )
    assert cli_result.exit_code == 1
    assert "Recette CLI invalide" in cli_result.output
    assert "invalid recorded parameters" in " ".join(cli_result.output.split())
    assert "Traceback" not in cli_result.output
    assert not target.exists()

    minimal_step = replace(
        recipe.steps[-1],
        args={
            key: value
            for key, value in recipe.steps[-1].args.items()
            if key != "profile"
        },
    )
    minimal_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], minimal_step),
    )
    with pytest.raises(RecipeError, match="Minimal application profile"):
        replay_recipe(
            minimal_recipe,
            minimal_recipe.steps,
            target_dir=target,
            strict=True,
        )

    save_recipe(minimal_recipe, project / "minimal-metadata.recipe.yaml")
    cli_result = runner.invoke(
        app,
        [
            "replay",
            str(project / "minimal-metadata.recipe.yaml"),
            "--dir",
            str(target),
            "--strict",
        ],
    )
    assert cli_result.exit_code == 1
    assert "Recette CLI invalide" in cli_result.output
    assert "Minimal application profile" in " ".join(cli_result.output.split())
    assert "Traceback" not in cli_result.output
    assert not target.exists()

    blueprint_only_step = replace(
        recipe.steps[-1],
        args={"entity": "Invoice", "blueprint": "state-machine"},
    )
    blueprint_only_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], blueprint_only_step),
    )
    with pytest.raises(RecipeError, match="Minimal application profile"):
        replay_recipe(
            blueprint_only_recipe,
            blueprint_only_recipe.steps,
            target_dir=target,
            strict=True,
        )

    assert not target.exists()

    unknown_step = replace(
        recipe.steps[-1],
        args={**recipe.steps[-1].args, "profile": "missing-blueprint"},
    )
    unknown_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], unknown_step),
    )
    save_recipe(unknown_recipe, project / "unknown.recipe.yaml")
    cli_result = runner.invoke(
        app,
        [
            "replay",
            str(project / "unknown.recipe.yaml"),
            "--dir",
            str(target),
            "--strict",
        ],
    )
    assert cli_result.exit_code == 1
    assert "Recette CLI invalide" in cli_result.output
    assert "invalid blueprint" in " ".join(cli_result.output.split())
    assert "Traceback" not in cli_result.output
    assert not target.exists()


def test_full_recipe_preflights_add_blueprint_metadata_before_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = runner.invoke(
        app,
        ["init", "blueprint-preflight-source", "--dir", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    project = tmp_path / "blueprint-preflight-source"
    _stateful_entity(project)
    spec_path = _write_spec(project)
    added = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "state-machine",
            "--entity",
            "Invoice",
            "--feature",
            "invoice_lifecycle",
            "--spec",
            str(spec_path),
        ],
    )
    assert added.exit_code == 0, added.output
    recipe = load_recipe(project / "arclith.recipe.yaml")
    incomplete_step = replace(
        recipe.steps[-1],
        args={
            key: value
            for key, value in recipe.steps[-1].args.items()
            if key != "parameters_digest"
        },
    )
    incomplete_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], incomplete_step),
    )
    target = tmp_path / "blueprint-preflight-target"

    with pytest.raises(RecipeError, match="replay requires both"):
        replay_recipe(
            incomplete_recipe,
            incomplete_recipe.steps,
            target_dir=target,
            strict=True,
        )

    assert not target.exists()

    missing_blueprint_step = replace(
        recipe.steps[-1],
        args={
            key: value
            for key, value in recipe.steps[-1].args.items()
            if key != "blueprint"
        },
    )
    missing_blueprint_recipe = replace(
        recipe,
        steps=(*recipe.steps[:-1], missing_blueprint_step),
    )
    with pytest.raises(RecipeError, match="non-empty string 'blueprint'"):
        replay_recipe(
            missing_blueprint_recipe,
            missing_blueprint_recipe.steps,
            target_dir=target,
            strict=True,
        )

    save_recipe(
        missing_blueprint_recipe,
        project / "missing-blueprint.recipe.yaml",
    )
    cli_result = runner.invoke(
        app,
        [
            "replay",
            str(project / "missing-blueprint.recipe.yaml"),
            "--dir",
            str(target),
            "--strict",
        ],
    )
    assert cli_result.exit_code == 1
    assert "Recette CLI invalide" in cli_result.output
    assert "non-empty string 'blueprint'" in " ".join(cli_result.output.split())
    assert "Traceback" not in cli_result.output
    assert not target.exists()


def test_fresh_state_machine_project_compiles_and_runs_generated_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    framework_root = Path(__file__).resolve().parents[2]
    project = _project(tmp_path, "runtime-invoice-service")
    spec_path = _write_spec(project)
    result = _invoke(
        monkeypatch,
        project,
        [
            "add-entity",
            "Invoice",
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )
    assert result.exit_code == 0, result.output
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(project / "src"), str(framework_root))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    for command in (
        [sys.executable, "-m", "compileall", "-q", "src"],
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        [sys.executable, "-m", "pytest", "-p", "pytest_asyncio.plugin", "tests", "-q"],
    ):
        completed = subprocess.run(
            command,
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_new_state_machine_profile_records_portable_parameters(tmp_path: Path) -> None:
    spec_path = tmp_path / "invoice-lifecycle.yaml"
    spec_path.write_text(
        yaml.safe_dump(_spec_document(), sort_keys=False),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "new",
            "Invoice",
            "new-invoice-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    project = tmp_path / "new-invoice-service"
    manifest = load_feature_manifest(project / ".arclith/features/invoice.yaml")
    recipe = load_recipe(project / "arclith.recipe.yaml")
    assert manifest.version == 2
    assert recipe.steps[0].command == "new"
    assert recipe.steps[0].args["parameters"] == manifest.parameters
    assert "spec" not in recipe.steps[0].args

    recorded = recipe.steps[0]
    drifted_step = replace(
        recorded,
        args={
            **recorded.args,
            "template_digest": "sha256:" + "0" * 64,
        },
    )
    drifted_recipe = replace(recipe, steps=(drifted_step,))
    drift_target = tmp_path / "new-digest-drift"
    with pytest.raises(ValueError, match="template digest drift"):
        replay_recipe(
            drifted_recipe,
            drifted_recipe.steps,
            target_dir=drift_target,
            strict=True,
        )
    assert not drift_target.exists()


@pytest.mark.parametrize("profile", ["minimal", "state-machine"])
def test_new_rejects_keyword_entity_before_initialization(
    tmp_path: Path,
    profile: str,
) -> None:
    spec_path = _write_spec(tmp_path)
    target = tmp_path / f"invalid-{profile}-service"
    arguments = [
        "new",
        "Class",
        target.name,
        "--dir",
        str(tmp_path),
        "--profile",
        profile,
    ]
    if profile == "state-machine":
        arguments.extend(("--spec", str(spec_path)))

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert "Blueprint refusé" in result.output
    assert "reserved Python keyword" in result.output
    assert "Traceback" not in result.output
    assert not target.exists()


def test_new_state_machine_entity_name_does_not_collide_with_state_module(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "invoice-lifecycle.yaml"
    spec_path.write_text(
        yaml.safe_dump(_spec_document(), sort_keys=False),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "new",
            "InvoiceLifecycleState",
            "lifecycle-state-service",
            "--dir",
            str(tmp_path),
            "--profile",
            "state-machine",
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    models = (
        tmp_path / "lifecycle-state-service/src/lifecycle_state_service/domain/models"
    )
    entity = models / "invoice_lifecycle_state.py"
    state = models / "invoice_lifecycle_state_lifecycle_state.py"
    assert entity.is_file()
    assert state.is_file()
    assert entity != state


def test_state_machine_requires_spec_and_non_parameterized_blueprints_reject_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    add_entity_cmd(project_dir=project, entity_name="Invoice")

    missing = _invoke(
        monkeypatch,
        project,
        ["add-blueprint", "state-machine", "--entity", "Invoice"],
    )
    extra = _invoke(
        monkeypatch,
        project,
        [
            "add-blueprint",
            "crud",
            "--entity",
            "Invoice",
            "--spec",
            str(_write_spec(project)),
        ],
    )

    assert missing.exit_code == 1
    assert "requires --spec" in missing.output
    assert extra.exit_code == 1
    assert "does not accept --spec" in extra.output
