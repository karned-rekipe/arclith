"""Typed synchronization composition. Source adapters and mapping stay explicit."""

from pathlib import Path
from textwrap import dedent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames
from arclith_cli.synchronization_spec import SynchronizationSpec

_OPERATIONS = (
    ("start_sync", "StartSync", "Command"),
    ("get_sync_status", "GetSyncStatus", "Query"),
    ("cancel_sync", "CancelSync", "Command"),
    ("get_sync_report", "GetSyncReport", "Query"),
)


def render_synchronization_blueprint(
    paths: ProjectPaths, entity: EntityInfo, feature: str, spec: SynchronizationSpec
) -> dict[Path, str]:
    name = EntityNames.from_input(feature).pascal
    # Validate the actual scope before any generated file is written.
    type(spec.definition).model_validate({**spec.to_parameters(), "name": feature})
    model = paths.import_path("domain", "models", feature)
    mapper = paths.import_path("application", "synchronization", f"{feature}_mapper")
    container = paths.import_path("infrastructure", "containers", feature)
    outbound = paths.import_path("domain", "ports", "outbound")
    files = {
        paths.domain_models / f"{feature}.py": _models(name, spec, entity),
        paths.package_root
        / "application"
        / "synchronization"
        / f"{feature}_mapper.py": _mapper(name, model),
        paths.containers / f"{feature}.py": _container(
            paths, feature, name, spec, model, mapper, outbound
        ),
        paths.root
        / "tests"
        / "application"
        / f"test_{feature}_synchronization.py": _tests(
            name, feature, spec, model, mapper, container, outbound
        ),
        paths.root
        / "docs"
        / "blueprints"
        / f"{feature}-synchronization.md": _documentation(feature, spec, entity),
    }
    for role, base in (
        ("source", f"SyncSourcePort[{name}Source]"),
        ("target", f"SyncTargetPort[{name}Fields]"),
        ("checkpoint", "SyncCheckpointPort"),
    ):
        model_import = ""
        if role != "checkpoint":
            suffix = "Source" if role == "source" else "Fields"
            model_import = f"from {model} import {name}{suffix}\n"
        files[
            paths.package_root
            / "domain"
            / "ports"
            / "outbound"
            / f"{feature}_{role}.py"
        ] = (
            f"from arclith.domain.ports.outbound.synchronization import {base.split('[')[0]}\n"
            + model_import
            + "\n\n"
            + f"class {name}{role.title()}Port({base}):\n"
            + f'    """Project-owned {role} adapter; implement the framework contract explicitly."""\n'
        )
    for operation, prefix, kind in _OPERATIONS:
        cls = prefix + name
        port = paths.import_path("domain", "ports", "inbound", f"{operation}_{feature}")
        files[paths.inbound_ports / f"{operation}_{feature}.py"] = _port(
            operation, cls, kind
        )
        files[paths.application_use_cases / f"{operation}_{feature}.py"] = _use_case(
            operation, cls, kind, port
        )
    return with_package_initializers(paths, files)


def _models(name: str, spec: SynchronizationSpec, entity: EntityInfo) -> str:
    key = spec.definition.external_key
    return dedent(f'''\
        from pydantic import BaseModel as _BaseModel, ConfigDict as _ConfigDict, Field as _Field


        class {name}Source(_BaseModel):
            """Define the source schema for {entity.pascal}; keep credentials outside it."""
            model_config = _ConfigDict(frozen=True, extra="forbid")
            {key}: str = _Field(min_length=1, max_length=255)


        class {name}Fields(_BaseModel):
            """Define only fields the source may own; the mapper selects them explicitly.

            The external key is the initial identity field. Extend this schema and
            implement the target adapter to map these fields to {entity.pascal}.
            The blueprint never rewrites the existing entity or its repository.
            """
            model_config = _ConfigDict(frozen=True, extra="forbid")
            {key}: str = _Field(min_length=1, max_length=255)
        ''')


def _mapper(name: str, model: str) -> str:
    return dedent(f'''\
        from arclith.domain.models.synchronization import SyncMapping
        from arclith.domain.ports.outbound.synchronization import SyncMapper
        from {model} import {name}Source, {name}Fields


        class {name}Mapper(SyncMapper[{name}Source, {name}Fields]):
            def map(self, source: {name}Source) -> SyncMapping[{name}Fields] | None:
                """Define ownership, normalization and deliberate skips for this project."""
                raise NotImplementedError("Implement the project synchronization mapping")
        ''')


def _port(operation: str, cls: str, kind: str) -> str:
    fields = "job_id: JobId"
    if operation == "start_sync":
        fields = "mode: SyncMode\n    idempotency_key: str | None = None\n    max_attempts: int = Field(default=1, ge=1, le=100, strict=True)"
    result = (
        "job_id: JobId"
        if operation == "start_sync"
        else (
            "report: SyncReport"
            if operation == "get_sync_report"
            else "job: JobRecord[SyncRequest, SyncReport]"
        )
    )
    model_imports = "from pydantic import BaseModel, ConfigDict\n"
    job_imports = "from arclith.domain.models.job import JobId\n"
    sync_imports = "from arclith.domain.models.synchronization import SyncReport\n"
    if operation == "start_sync":
        model_imports = "from pydantic import BaseModel, ConfigDict, Field\n"
        sync_imports = "from arclith.domain.models.synchronization import SyncMode\n"
    elif operation != "get_sync_report":
        job_imports = "from arclith.domain.models.job import JobId, JobRecord\n"
        sync_imports = "from arclith.domain.models.synchronization import SyncRequest, SyncReport\n"
    return (
        "from abc import ABC, abstractmethod\n"
        + model_imports
        + job_imports
        + sync_imports
        + "\n\n"
        + f"class {cls}{kind}(BaseModel):\n"
        '    model_config = ConfigDict(frozen=True, extra="forbid")\n'
        f"    {fields}\n\n\n"
        f"class {cls}Result(BaseModel):\n"
        '    model_config = ConfigDict(frozen=True, extra="forbid")\n'
        f"    {result}\n\n\n"
        f"class {cls}Port(ABC):\n"
        "    @abstractmethod\n"
        f"    async def execute(self, request: {cls}{kind}) -> {cls}Result:\n"
        '        """Execute the typed synchronization operation."""\n'
    )


def _use_case(operation: str, cls: str, kind: str, port: str) -> str:
    args = "request.job_id"
    field = "report" if operation == "get_sync_report" else "job"
    if operation == "start_sync":
        args = "request.mode, idempotency_key=request.idempotency_key, max_attempts=request.max_attempts"
        field = "job_id"
    return dedent(f"""\
        from arclith.application.services.synchronization import SynchronizationService
        from {port} import {cls}{kind}, {cls}Result, {cls}Port


        class {cls}UseCase({cls}Port):
            def __init__(self, service: SynchronizationService) -> None:
                self._service = service

            async def execute(self, request: {cls}{kind}) -> {cls}Result:
                value = await self._service.{operation}({args})
                return {cls}Result({field}=value)
        """)


def _container(
    paths: ProjectPaths,
    feature: str,
    name: str,
    spec: SynchronizationSpec,
    model: str,
    mapper: str,
    outbound: str,
) -> str:
    imports = "\n".join(
        f"from {paths.import_path('application', 'use_cases', operation + '_' + feature)} import {prefix}{name}UseCase"
        for operation, prefix, _ in _OPERATIONS
    )
    bindings = "\n".join(
        f"        self.{operation} = {prefix}{name}UseCase(service)"
        for operation, prefix, _ in _OPERATIONS
    )
    return (
        dedent(f"""\
        from arclith.application.services.job_service import JobService
        from arclith.application.services.synchronization import SyncJobHandler, SynchronizationService
        from arclith.domain.models.synchronization import SyncDefinition, SyncRequest, SyncReport
        from arclith.domain.ports.outbound.job_runner import JobRunnerPort
        from arclith.domain.ports.outbound.job_store import JobStorePort
        from {model} import {name}Source, {name}Fields
        from {mapper} import {name}Mapper
        from {outbound}.{feature}_source import {name}SourcePort
        from {outbound}.{feature}_target import {name}TargetPort
        from {outbound}.{feature}_checkpoint import {name}CheckpointPort
        """)
        + imports
        + "\n\n\n"
        + (
            f"DEFINITION = SyncDefinition(name={feature!r}, **{spec.to_parameters()!r})\n\n\n"
            f"def build_{feature}_handler(source: {name}SourcePort, target: {name}TargetPort,\n"
            f"        checkpoints: {name}CheckpointPort, mapper: {name}Mapper) -> SyncJobHandler[{name}Source, {name}Fields]:\n"
            '    """Wire this handler into the explicitly selected Job runner."""\n'
            f"    return SyncJobHandler(DEFINITION, source, target, mapper, checkpoints,\n"
            f"                          source_type={name}Source, target_type={name}Fields)\n\n\n"
            f"class {name}Container:\n"
            "    def __init__(self, runner: JobRunnerPort[SyncRequest, SyncReport],\n"
            f"                 store: JobStorePort[SyncRequest, SyncReport], checkpoints: {name}CheckpointPort) -> None:\n"
            "        service = SynchronizationService(DEFINITION, JobService(runner, store), checkpoints)\n"
            + bindings
            + "\n"
        )
    )


def _tests(
    name: str,
    feature: str,
    spec: SynchronizationSpec,
    model: str,
    mapper: str,
    container: str,
    outbound: str,
) -> str:
    key = spec.definition.external_key
    package = model.split(".domain.")[0]
    mode = spec.definition.modes[0]
    return dedent(f"""\
        import pytest
        from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
        from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
        from arclith.adapters.outbound.memory.synchronization import InMemorySyncTarget, InMemorySyncCheckpoint
        from arclith.domain.models.job import JobStatus
        from arclith.domain.models.synchronization import SourcePage, SyncMapping, SyncRequest, SyncReport
        from {model} import {name}Source, {name}Fields
        from {mapper} import {name}Mapper
        from {container} import {name}Container, build_{feature}_handler
        from {outbound}.{feature}_source import {name}SourcePort
        from {outbound}.{feature}_target import {name}TargetPort
        from {outbound}.{feature}_checkpoint import {name}CheckpointPort
        from {package}.domain.ports.inbound.start_sync_{feature} import StartSync{name}Command
        from {package}.domain.ports.inbound.get_sync_report_{feature} import GetSyncReport{name}Query
        from {package}.domain.ports.inbound.get_sync_status_{feature} import GetSyncStatus{name}Query
        from {package}.domain.ports.inbound.cancel_sync_{feature} import CancelSync{name}Command


        class SourceFake({name}SourcePort):
            async def fetch_page(self, *, mode, cursor, limit):
                return SourcePage(items=({name}Source({key}="demo"),), checkpoint_cursor="watermark")


        class TargetFake(InMemorySyncTarget[{name}Fields], {name}TargetPort):
            pass


        class CheckpointFake(InMemorySyncCheckpoint, {name}CheckpointPort):
            pass


        class MapperFake({name}Mapper):
            def map(self, source):
                # Test-only identity mapping; the production mapper stays unimplemented.
                return SyncMapping(value={name}Fields({key}=source.{key}), owned_fields=({key!r},))


        def compose(mapper):
            checkpoints = CheckpointFake()
            target = TargetFake({name}Fields)
            handler = build_{feature}_handler(SourceFake(), target, checkpoints, mapper)
            store = InMemoryJobStore(SyncRequest, SyncReport)
            runner = InMemoryJobRunner(store, handler)
            return {name}Container(runner, store, checkpoints), runner


        @pytest.mark.asyncio
        @pytest.mark.parametrize("mode", {list(spec.definition.modes)!r})
        async def test_fake_sync_and_idempotency(mode):
            container, runner = compose(MapperFake())
            command = StartSync{name}Command(mode=mode, idempotency_key="same")
            job_id = (await container.start_sync.execute(command)).job_id
            assert (await container.start_sync.execute(command)).job_id == job_id
            status = await container.get_sync_status.execute(GetSyncStatus{name}Query(job_id=job_id))
            assert status.job.status is JobStatus.QUEUED
            assert (await runner.run(job_id)).status is JobStatus.SUCCEEDED
            result = await container.get_sync_report.execute(GetSyncReport{name}Query(job_id=job_id))
            assert result.report.complete and result.report.created == 1


        @pytest.mark.asyncio
        async def test_production_mapper_does_not_fake_success():
            container, runner = compose({name}Mapper())
            result = await container.start_sync.execute(StartSync{name}Command(mode={mode!r}))
            assert (await runner.run(result.job_id)).status is JobStatus.FAILED
            report = await container.get_sync_report.execute(GetSyncReport{name}Query(job_id=result.job_id))
            assert report.report.errors[0].code == "mapping_failed"


        @pytest.mark.asyncio
        async def test_queued_cancellation():
            container, runner = compose(MapperFake())
            result = await container.start_sync.execute(StartSync{name}Command(mode={mode!r}))
            cancelled = await container.cancel_sync.execute(CancelSync{name}Command(job_id=result.job_id))
            assert cancelled.job.status is JobStatus.CANCELLED
        """)


def _documentation(feature: str, spec: SynchronizationSpec, entity: EntityInfo) -> str:
    return dedent(f"""\
        # Synchronization `{feature}`

        Pull reconciliation for `{entity.pascal}`. Parameters: `{spec.to_parameters()!r}`.

        Implement the source, target and checkpoint ports and the explicit mapper.
        The generated source/patch models contain only the external identity field;
        extend them with the schema and source-owned fields required by your project.
        The existing entity is never rewritten. The production mapper raises
        NotImplementedError until implemented; tests use a deliberate local fake.

        Wire `build_{feature}_handler` into a JobRunnerPort and inject that runner,
        its JobStorePort and the checkpoint adapter into the container. Scheduling
        belongs to the chosen runner. The memory runner needs `await run(job_id)`.
        No adapter or transport is selected automatically.

        A partial page never advances the incremental cursor; reapplying already
        applied items must have no second effect. Full sync restarts from the
        beginning after failure and limits seen keys to {spec.definition.max_full_items}.
        Missing records are deactivated atomically only after all pages succeed.
        Source-owned fields are the mapper's explicit `owned_fields`; local fields
        remain unchanged. A skipped source key still counts as seen during full sync.

        Terminal incremental pages must supply a non-secret `checkpoint_cursor`,
        distinct from `next_cursor=None`. The full scan must be exhaustive and stable
        before using deactivate. Keep source_version stable; a schema/source change
        needs an explicit checkpoint migration or a new sync scope.

        get_sync_status returns JobRecord; get_sync_report also works after partial
        failure. Counters describe this attempt, including already applied items
        as unchanged on retry. Retry uses the Job contract with the same JobId and
        an explicit max_attempts budget (default 1). Cancellation is cooperative
        between pages. Reports contain bounded codes/positions, never raw exceptions.

        Memory adapters are non-durable development references. The checkpoint store
        keeps up to 1000 job reports by default; explicitly delete old reports.
        Production adapters must provide durable CAS, exclusive claims and idempotent
        target writes/finalization. No push, bidirectional sync, hard-delete or CDC.
        """)
