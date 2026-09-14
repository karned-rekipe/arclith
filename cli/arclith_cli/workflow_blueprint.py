"""Render explicit sequential workflow extension points and typed operations."""

import ast
from pathlib import Path
from textwrap import dedent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames
from arclith_cli.workflow_spec import WorkflowSpec

_OPERATIONS = (
    ("start", "Start", "Command"),
    ("get_status", "GetStatus", "Query"),
    ("cancel", "Cancel", "Command"),
    ("resume", "Resume", "Command"),
    ("get_result", "GetResult", "Query"),
)


def render_workflow_blueprint(
    paths: ProjectPaths, entity: EntityInfo | None, feature: str, spec: WorkflowSpec
) -> dict[Path, str]:
    from arclith.domain.models.workflow import WorkflowDefinition

    WorkflowDefinition(
        name=feature,
        version=spec.definition_version,
        context=spec.context,
        result=spec.result,
        steps=[{"name": n, "max_attempts": a} for n, a in spec.steps],
    )
    name = EntityNames.from_input(feature).pascal
    models = paths.import_path("domain", "models", f"{feature}_workflow")
    workflow = paths.import_path("application", "workflows", feature)
    base = paths.package_root / "application" / "workflows" / feature
    files = {
        paths.domain_models / f"{feature}_workflow.py": _models(spec, entity),
        base / "definition.py": _definition(feature, spec),
        base / "context.py": _result_mapper(spec, models),
        paths.containers / f"{feature}.py": _container(
            paths, feature, name, spec, models, workflow
        ),
        paths.root / "tests" / "application" / f"test_{feature}_workflow.py": _tests(
            paths, feature, name, spec, models, workflow, entity
        ),
        paths.root / "docs" / "blueprints" / f"{feature}-workflow.md": _documentation(
            feature, spec
        ),
    }
    for step, _ in spec.steps:
        step_class = EntityNames.from_input(step).pascal + "Step"
        files[base / "steps" / f"{step}.py"] = dedent(f'''\
            from arclith.domain.ports.outbound.workflow_runner import StepExecutionContext, WorkflowStep
            from {models} import {spec.context} as _Context


            class {step_class}(WorkflowStep[_Context]):
                name = {step!r}

                async def execute(self, context: _Context, *, execution: StepExecutionContext) -> _Context:
                    """Implement this step and deduplicate effects using execution.execution_key."""
                    raise NotImplementedError("Implement the workflow step")
        ''')
    for operation, prefix, kind in _OPERATIONS:
        class_name = prefix + name
        port = paths.import_path("domain", "ports", "inbound", f"{operation}_{feature}")
        files[paths.inbound_ports / f"{operation}_{feature}.py"] = _port(
            operation, class_name, kind, spec, models
        )
        files[paths.application_use_cases / f"{operation}_{feature}.py"] = _use_case(
            operation, class_name, kind, spec, models, port
        )
    return with_package_initializers(
        paths,
        {
            path: _format_imports(content, paths.package_name)
            if path.suffix == ".py"
            else content
            for path, content in files.items()
        },
    )


def _format_imports(content: str, package: str) -> str:
    """Keep generated import blocks stable for arbitrary public class/feature names.

    Only our generated leading imports are inspected; no user code is executed
    or rewritten, and no formatter executable is needed at generation time.
    """
    imports: dict[tuple[int, str], list[tuple[str, str | None]]] = {}
    plain: dict[int, list[str]] = {}
    end = 0
    separator = "\n\n\n"
    for node in ast.parse(content).body:
        if isinstance(node, ast.Import):
            plain.setdefault(1, []).extend(f"import {item.name}" for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            root = node.module.split(".")[0]
            group = (
                0
                if root in {"abc", "dataclasses", "uuid"}
                else 2
                if root == package.split(".")[0]
                else 1
            )
            imports.setdefault((group, node.module), []).extend(
                (item.name, item.asname) for item in node.names
            )
        else:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                separator = "\n\n"
            break
        end = node.end_lineno or node.lineno
    blocks = []
    for group in range(3):
        lines = sorted(plain.get(group, []))
        for (category, module), names in sorted(imports.items()):
            if category != group:
                continue
            regular = sorted(
                {name for name, alias in names if alias is None}, key=str.casefold
            )
            aliases = sorted(
                {(name, alias) for name, alias in names if alias is not None},
                key=lambda item: item[0].casefold(),
            )
            members = ([regular] if regular else []) + [
                [f"{name} as {alias}"] for name, alias in aliases
            ]
            for items in members:
                line = f"from {module} import {', '.join(items)}"
                lines.append(
                    line
                    if len(line) <= 88
                    else f"from {module} import (\n"
                    + "".join(f"    {item},\n" for item in items)
                    + ")"
                )
        if lines:
            blocks.append("\n".join(lines))
    return (
        "\n\n".join(blocks)
        + separator
        + "\n".join(content.splitlines()[end:]).lstrip("\n")
        + "\n"
    )


def _models(spec: WorkflowSpec, entity: EntityInfo | None) -> str:
    imports = (
        "from pydantic import BaseModel as _BaseModel, ConfigDict as _ConfigDict\n"
    )
    fields = ""
    if entity is not None:
        imports += "from uuid import UUID as _UUID\nfrom pydantic import field_validator as _field_validator\n"
        fields = f"""    # Reference to {entity.pascal}; authorization/existence belongs to the steps.
    entity_id: str

    @_field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        return str(_UUID(value))
"""
    return (
        imports
        + f'''\n\nclass {spec.context}(_BaseModel):
    """Define bounded JSON-native business context or external references."""
    model_config = _ConfigDict(frozen=True, extra="forbid")
{fields}

class {spec.result}(_BaseModel):
    """Define the small final result; no implicit business projection."""
    model_config = _ConfigDict(frozen=True, extra="forbid")
'''
    )


def _definition(feature: str, spec: WorkflowSpec) -> str:
    steps = "\n".join(
        f"        WorkflowStepDefinition(name={name!r}, max_attempts={attempts}),"
        for name, attempts in spec.steps
    )
    return f"""from arclith.domain.models.workflow import WorkflowDefinition, WorkflowStepDefinition

DEFINITION = WorkflowDefinition(
    name={feature!r}, version={spec.definition_version}, context={spec.context!r}, result={spec.result!r},
    steps=(
{steps}
    ),
)
"""


def _result_mapper(spec: WorkflowSpec, models: str) -> str:
    return dedent(f'''\
        from arclith.domain.ports.outbound.workflow_runner import WorkflowResultMapper
        from {models} import {spec.context} as _Context, {spec.result} as _Result


        class ResultMapper(WorkflowResultMapper[_Context, _Result]):
            def build_result(self, context: _Context) -> _Result:
                """Implement a pure, deterministic projection without external effects."""
                raise NotImplementedError("Implement the workflow result projection")
    ''')


def _port(operation: str, name: str, kind: str, spec: WorkflowSpec, models: str) -> str:
    fields = (
        "    context: _Context\n    idempotency_key: str | None = None"
        if operation == "start"
        else "    workflow_id: WorkflowId"
    )
    output = (
        "    workflow_id: WorkflowId"
        if operation == "start"
        else "    result: _Result"
        if operation == "get_result"
        else "    workflow: WorkflowInstance[_Context, _Result]"
    )
    workflow_import = "WorkflowId" + (
        ", WorkflowInstance" if operation not in {"start", "get_result"} else ""
    )
    model_import = (
        f"{spec.context} as _Context"
        if operation == "start"
        else f"{spec.result} as _Result"
        if operation == "get_result"
        else f"{spec.context} as _Context, {spec.result} as _Result"
    )
    return f'''from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict
from arclith.domain.models.workflow import {workflow_import}
from {models} import {model_import}


class {name}{kind}(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
{fields}


class {name}Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
{output}


class {name}Port(ABC):
    @abstractmethod
    async def execute(self, request: {name}{kind}) -> {name}Result:
        """Execute the typed workflow operation."""
        raise NotImplementedError
'''


def _use_case(
    operation: str, name: str, kind: str, spec: WorkflowSpec, models: str, port: str
) -> str:
    field = (
        "workflow_id"
        if operation == "start"
        else "result"
        if operation == "get_result"
        else "workflow"
    )
    args = (
        "request.context, idempotency_key=request.idempotency_key"
        if operation == "start"
        else "request.workflow_id"
    )
    return dedent(f"""\
        from arclith.application.services.workflow_service import WorkflowService
        from {models} import {spec.context} as _Context, {spec.result} as _Result
        from {port} import {name}{kind}, {name}Port, {name}Result


        class {name}UseCase({name}Port):
            def __init__(self, service: WorkflowService[_Context, _Result]) -> None:
                self._service = service

            async def execute(self, request: {name}{kind}) -> {name}Result:
                return {name}Result({field}=await self._service.{operation}({args}))
    """)


def _container(
    paths: ProjectPaths,
    feature: str,
    name: str,
    spec: WorkflowSpec,
    models: str,
    workflow: str,
) -> str:
    imports, fields, args = [], [], []
    for operation, prefix, _ in _OPERATIONS:
        op = prefix + name
        imports += [
            f"from {paths.import_path('domain', 'ports', 'inbound', operation + '_' + feature)} import {op}Port",
            f"from {paths.import_path('application', 'use_cases', operation + '_' + feature)} import {op}UseCase",
        ]
        fields.append(f"    {operation}: {op}Port")
        args.append(f"        {operation}={op}UseCase(service),")
    return (
        """from dataclasses import dataclass
from arclith.application.services.workflow_service import WorkflowService
from arclith.domain.ports.outbound.workflow_runner import WorkflowRunnerPort
from arclith.domain.ports.outbound.workflow_store import WorkflowStorePort
"""
        + f"from {models} import {spec.context} as _Context, {spec.result} as _Result\nfrom {workflow}.definition import DEFINITION\n"
        + "\n".join(imports)
        + f"""


@dataclass(frozen=True)
class {name}UseCases:
"""
        + "\n".join(fields)
        + f'''


def build_{feature}_use_cases(runner: WorkflowRunnerPort[_Context, _Result], store: WorkflowStorePort[_Context, _Result]) -> {name}UseCases:
    """Inject a runner and its store; no scheduler or adapter is installed."""
    service = WorkflowService(DEFINITION, runner, store)
    return {name}UseCases(
'''
        + "\n".join(args)
        + "\n    )\n"
    )


def _tests(
    paths: ProjectPaths,
    feature: str,
    name: str,
    spec: WorkflowSpec,
    models: str,
    workflow: str,
    entity: EntityInfo | None,
) -> str:
    context_args = (
        'entity_id="01951234-5678-7abc-8ef0-123456789abc"' if entity is not None else ""
    )
    container = paths.import_path("infrastructure", "containers", feature)
    start_port = paths.import_path("domain", "ports", "inbound", f"start_{feature}")
    result_port = paths.import_path(
        "domain", "ports", "inbound", f"get_result_{feature}"
    )
    return dedent(f"""\
        import pytest
        from arclith.adapters.outbound.memory.workflow_store import InMemoryWorkflowStore
        from arclith.adapters.outbound.memory.workflow_runner import InMemoryWorkflowRunner
        from arclith.domain.errors.workflow import WorkflowTransitionError
        from arclith.domain.models.workflow import WorkflowStatus
        from arclith.domain.ports.outbound.workflow_runner import WorkflowStep, WorkflowResultMapper
        from {models} import {spec.context} as _Context, {spec.result} as _Result
        from {workflow}.definition import DEFINITION
        from {container} import build_{feature}_use_cases
        from {start_port} import Start{name}Command
        from {result_port} import GetResult{name}Query


        class FakeStep(WorkflowStep[_Context]):
            def __init__(self, name, calls, fail=False):
                self._name, self.calls, self.fail = name, calls, fail

            @property
            def name(self):
                return self._name

            async def execute(self, context, *, execution):
                self.calls.append((self.name, execution.execution_key))
                if self.fail:
                    self.fail = False
                    raise RuntimeError("deterministic fake failure")
                return context


        class FakeResult(WorkflowResultMapper[_Context, _Result]):
            def build_result(self, context):
                return _Result()


        def setup(fail=False):
            calls = []
            store = InMemoryWorkflowStore(_Context, _Result)
            failure_index = next((i for i, step in enumerate(DEFINITION.steps) if step.max_attempts > 1), 0)
            steps = [FakeStep(step.name, calls, fail and i == failure_index) for i, step in enumerate(DEFINITION.steps)]
            runner = InMemoryWorkflowRunner(DEFINITION, store, steps, FakeResult(), context_type=_Context, result_type=_Result)
            return calls, store, runner, build_{feature}_use_cases(runner, store)


        @pytest.mark.asyncio
        async def test_order_and_typed_operations():
            calls, _store, runner, use_cases = setup()
            command = Start{name}Command(context=_Context({context_args}), idempotency_key="first")
            started = await use_cases.start.execute(command)
            assert (await use_cases.start.execute(command)).workflow_id == started.workflow_id
            record = await runner.run(started.workflow_id)
            assert record.status is WorkflowStatus.COMPLETED
            assert [name for name, key in calls] == [step.name for step in DEFINITION.steps]
            assert record.checkpoint == len(DEFINITION.steps)
            assert (await use_cases.get_result.execute(GetResult{name}Query(workflow_id=started.workflow_id))).result == _Result()


        @pytest.mark.asyncio
        async def test_failure_and_explicit_resume_budget():
            calls, _store, runner, use_cases = setup(fail=True)
            failure_index = next((i for i, step in enumerate(DEFINITION.steps) if step.max_attempts > 1), 0)
            started = await use_cases.start.execute(Start{name}Command(context=_Context({context_args})))
            failed = await runner.run(started.workflow_id)
            assert failed.status is WorkflowStatus.FAILED and failed.checkpoint == failure_index
            if DEFINITION.steps[failure_index].max_attempts > 1:
                assert (await runner.resume(started.workflow_id)).status is WorkflowStatus.COMPLETED
                assert calls[failure_index][1] == calls[failure_index + 1][1]
                for confirmed in DEFINITION.steps[:failure_index]:
                    assert sum(name == confirmed.name for name, key in calls) == 1
            else:
                with pytest.raises(WorkflowTransitionError):
                    await runner.resume(started.workflow_id)
    """)


def _documentation(feature: str, spec: WorkflowSpec) -> str:
    names = ", ".join(name for name, _ in spec.steps)
    return f"""# Workflow `{feature}`

Sequential steps: {names}. Definition version: {spec.definition_version}.
Complete each production step and the pure result mapper before business use.
Tests inject independent deterministic fakes; they do not publish or notify.

Compose `InMemoryWorkflowStore`, `InMemoryWorkflowRunner`, the generated
`DEFINITION`, steps and result mapper, then `build_{feature}_use_cases`.
Start persists pending work; await `runner.run(id)` to execute it.
Resume executes immediately and consumes the next attempt of an unconfirmed
step. Default max_attempts=1 forbids retry; there is no automatic retry.
Confirmed steps are not replayed. External effects before a lost checkpoint may
be repeated: deduplicate using `execution.execution_key`, stable across attempts.
Result projection is pure and can be repeated after every step is confirmed.

Context/result: JSON-native Pydantic models, 64 KiB and 32 levels each, no secrets.
Use identifiers for files/large outputs. A schema or definition mismatch prevents
execution/resume. Increment definition_version when step semantics change.
Cancellation is cooperative between steps; an in-flight step may finish. A
cancelled workflow cannot resume. An unconfirmed step can retain running status
in a cancelled record; that indicates uncertainty, not a background task.

The memory store is non-durable, one asyncio loop, at most 1000 instances by
default; explicit delete_terminal also removes idempotency-key retention.
Progress reuses JobProgress counters. Only the last 200 metadata events are kept.
Durable adapters must atomically persist context/checkpoint, enforce CAS and
exclusive ownership, and fence old workers before recovery. No implicit lease,
scheduler, DAG, timers, saga, transport or production engine is installed.
See the framework Pages guide for executable composition and production limits.
"""
