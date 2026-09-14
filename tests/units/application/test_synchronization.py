import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field, SecretStr, ValidationError

from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
from arclith.adapters.outbound.memory.synchronization import (
    InMemorySyncCheckpoint,
    InMemorySyncTarget,
)
from arclith.application.services.job_service import JobService
from arclith.application.services.synchronization import (
    SyncJobHandler,
    SynchronizationService,
)
from arclith.domain.errors.job import JobIdempotencyConflict, JobTransitionError
from arclith.domain.errors.synchronization import (
    SyncBusy,
    SyncReportUnavailable,
    SyncVersionConflict,
)
from arclith.domain.models.job import JobProgress, JobStatus
from arclith.domain.models.synchronization import (
    SourcePage,
    SyncChange,
    SyncDefinition,
    SyncItemError,
    SyncMapping,
    SyncReport,
    SyncRequest,
)
from arclith.domain.ports.outbound.synchronization import SyncMapper, SyncSourcePort

NOW = datetime(2026, 9, 14, tzinfo=UTC)


class Source(BaseModel):
    external_id: str | None = None
    name: str = "source"


class Target(BaseModel):
    name: str = ""
    local: str = ""


class SourceFake(SyncSourcePort[Source]):
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.fail = None

    async def fetch_page(self, *, mode, cursor, limit):
        self.calls.append((mode, cursor, limit))
        if self.fail == cursor and self.fail is not None:
            raise RuntimeError("password=never-show-this")
        return self.pages[cursor]


class Mapper(SyncMapper[Source, Target]):
    def __init__(self):
        self.fail = None
        self.skip = None

    def map(self, source):
        if source.external_id == self.fail:
            raise RuntimeError("password=never-show-this")
        if source.external_id == self.skip:
            return None
        return SyncMapping(value=Target(name=source.name), owned_fields=("name",))


def page(*ids, next_cursor=None, watermark=None):
    return SourcePage(
        items=tuple(Source(external_id=id_) for id_ in ids),
        next_cursor=next_cursor,
        checkpoint_cursor=watermark,
    )


def setup(pages=None, *, checkpoints=None, target=None, **config):
    definition = SyncDefinition(
        name="customer_sync", external_key="external_id", **config
    )
    source = SourceFake(
        pages if pages is not None else {None: page("a", watermark="done")}
    )
    mapper = Mapper()
    target = target or InMemorySyncTarget(Target)
    checkpoints = checkpoints or InMemorySyncCheckpoint()
    handler = SyncJobHandler(
        definition,
        source,
        target,
        mapper,
        checkpoints,
        source_type=Source,
        target_type=Target,
        clock=lambda: NOW,
    )
    store = InMemoryJobStore(SyncRequest, SyncReport)
    runner = InMemoryJobRunner(store, handler)
    jobs = JobService(runner, store)
    service = SynchronizationService(definition, jobs, checkpoints)
    return source, mapper, target, checkpoints, runner, service


async def seed(
    target, external_id, *, name="old", local="local", scope="customer_sync"
):
    return await target.apply(
        SyncChange(
            sync_name=scope,
            external_id=external_id,
            mapping=SyncMapping(
                value=Target(name=name, local=local), owned_fields=("name", "local")
            ),
        )
    )


async def test_partial_page_keeps_checkpoint_and_retry_resumes_without_double_effects():
    opaque = "opaque::page/2?x=%2F"
    source, mapper, target, checkpoints, runner, service = setup(
        {
            None: page("a", next_cursor=opaque),
            opaque: page("b", "c", watermark="watermark:3"),
            "watermark:3": page(watermark="watermark:3"),
        }
    )
    mapper.fail = "c"
    job_id = await service.start_sync("incremental", max_attempts=2)
    result = await runner.run(job_id)
    assert result.status is JobStatus.FAILED
    assert result.progress.completed == 1 and result.progress.percent is None
    checkpoint = await checkpoints.load("customer_sync")
    assert (
        checkpoint.last_successful_cursor == opaque
        and checkpoint.last_success_at is None
    )
    report = await service.get_sync_report(job_id)
    assert (report.created, report.failed, report.pages, report.complete) == (
        2,
        1,
        1,
        False,
    )
    assert report.errors == (SyncItemError(code="mapping_failed", page=1, item=1),)
    assert "password" not in report.model_dump_json() + result.model_dump_json()
    assert (await target.get_by_external_id("customer_sync", "b")).active

    mapper.fail = None
    await runner.retry(job_id)
    result = await runner.run(job_id)
    assert result.status is JobStatus.SUCCEEDED and result.attempt == 2
    report = await service.get_sync_report(job_id)
    assert (report.created, report.unchanged, report.failed, report.complete) == (
        1,
        1,
        0,
        True,
    )
    assert [call[1] for call in source.calls] == [None, opaque, opaque]
    checkpoint = await checkpoints.load("customer_sync")
    assert (
        checkpoint.last_successful_cursor == "watermark:3"
        and checkpoint.last_success_at == NOW
    )
    assert checkpoint.last_report == report
    next_job = await service.start_sync("incremental")
    await runner.run(next_job)
    assert source.calls[-1][1] == "watermark:3"


@pytest.mark.parametrize(
    "policy,active,count", [("ignore", True, 0), ("deactivate", False, 1)]
)
async def test_full_finalization_is_scoped_and_preserves_local_and_skipped_fields(
    policy, active, count
):
    source, mapper, target, checkpoints, runner, service = setup(
        {None: page("a", next_cursor="two"), "two": page("skip")},
        missing_policy=policy,
    )
    for key in ("a", "skip", "missing"):
        await seed(target, key)
    await seed(target, "other", scope="other_sync")
    mapper.skip = "skip"
    job_id = await service.start_sync("full")
    assert (await runner.run(job_id)).status is JobStatus.SUCCEEDED
    report = await service.get_sync_report(job_id)
    assert (report.updated, report.skipped, report.deactivated, report.pages) == (
        1,
        1,
        count,
        2,
    )
    assert (await target.get_by_external_id("customer_sync", "a")).fields == {
        "name": "source",
        "local": "local",
    }
    assert (await target.get_by_external_id("customer_sync", "skip")).active
    assert (
        await target.get_by_external_id("customer_sync", "missing")
    ).active is active
    assert (await target.get_by_external_id("other_sync", "other")).active
    assert (await checkpoints.load("customer_sync")).last_successful_cursor is None
    again = await service.start_sync("full")
    await runner.run(again)
    report = await service.get_sync_report(again)
    assert (report.unchanged, report.deactivated) == (1, 0)


async def test_full_restart_reads_all_pages_before_deactivating():
    source, mapper, target, checkpoints, runner, service = setup(
        {
            None: page("a", next_cursor="two"),
            "two": page("b"),
        },
        missing_policy="deactivate",
    )
    await seed(target, "missing")
    mapper.fail = "b"
    job_id = await service.start_sync("full", max_attempts=2)
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await target.get_by_external_id("customer_sync", "missing")).active
    mapper.fail = None
    await runner.retry(job_id)
    assert (await runner.run(job_id)).status is JobStatus.SUCCEEDED
    assert [call[1] for call in source.calls] == [None, "two", None, "two"]
    assert not (await target.get_by_external_id("customer_sync", "missing")).active
    assert (await target.get_by_external_id("customer_sync", "a")).active


@pytest.mark.parametrize(
    "failure", ["source", "mapping", "target", "checkpoint", "limit", "cycle"]
)
async def test_failed_full_never_sweeps_missing(failure):
    class TargetFailure(InMemorySyncTarget[Target]):
        async def apply(self, change):
            if change.external_id == "b":
                raise RuntimeError("password=secret")
            return await super().apply(change)

    class CommitFailure(InMemorySyncCheckpoint):
        async def commit(self, checkpoint, **kwargs):
            if checkpoint.last_report.pages == 2:
                raise OSError("secret")
            return await super().commit(checkpoint, **kwargs)

    source, mapper, target, checkpoints, runner, service = setup(
        {
            None: page("a", next_cursor="two"),
            "two": page("b", next_cursor="two" if failure == "cycle" else None),
        },
        missing_policy="deactivate",
        max_full_items=1 if failure == "limit" else 100,
        target=TargetFailure(Target) if failure == "target" else None,
        checkpoints=CommitFailure() if failure == "checkpoint" else None,
    )
    await seed(target, "missing")
    if failure == "source":
        source.fail = "two"
    if failure == "mapping":
        mapper.fail = "b"
    job_id = await service.start_sync("full")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await target.get_by_external_id("customer_sync", "missing")).active
    report = await service.get_sync_report(job_id)
    assert not report.complete and report.failed == 1
    assert "secret" not in report.model_dump_json()
    if failure == "checkpoint":
        assert report.pages == 1 and report.errors[0].page == 1
    assert (await checkpoints.load("customer_sync")).last_success_at is None


async def test_idempotent_submit_and_exclusive_scope_claims():
    source, mapper, target, checkpoints, runner, service = setup()
    ids = await asyncio.gather(
        *(service.start_sync("incremental", idempotency_key="same") for _ in range(20))
    )
    assert len(set(ids)) == 1
    with pytest.raises(JobIdempotencyConflict):
        await service.start_sync("full", idempotency_key="same")
    owner = uuid4()
    await checkpoints.claim("customer_sync", "1", owner)
    assert (await runner.run(ids[0])).status is JobStatus.FAILED
    assert (await service.get_sync_report(ids[0])).errors[0].code == "sync_busy"
    assert not source.calls
    await checkpoints.release("customer_sync", owner)


async def test_cancellation_between_pages_preserves_committed_cursor_and_report():
    source, mapper, target, checkpoints, runner, service = setup(
        {
            None: page("a", next_cursor="two"),
            "two": page("b", watermark="done"),
        }
    )
    original = checkpoints.commit

    async def cancel_after_commit(checkpoint, **kwargs):
        result = await original(checkpoint, **kwargs)
        await service.cancel_sync(kwargs["owner"])
        return result

    checkpoints.commit = cancel_after_commit
    job_id = await service.start_sync("incremental")
    assert (await runner.run(job_id)).status is JobStatus.CANCELLED
    assert len(source.calls) == 1
    assert (await checkpoints.load("customer_sync")).last_successful_cursor == "two"
    assert (await service.get_sync_report(job_id)).errors[0].code == "cancelled"
    # Cancellation released the claim.
    owner = uuid4()
    await checkpoints.claim("customer_sync", "1", owner)
    await checkpoints.release("customer_sync", owner)


async def test_owner_task_cancellation_records_report_and_releases_claim():
    source, mapper, target, checkpoints, runner, service = setup()
    entered = asyncio.Event()

    async def waiting(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    source.fetch_page = waiting
    job_id = await service.start_sync("incremental")
    task = asyncio.create_task(runner.run(job_id))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await service.get_sync_report(job_id)).errors[0].code == "interrupted"
    await checkpoints.claim("customer_sync", "1", uuid4())


@pytest.mark.parametrize(
    "pages,config",
    [
        ({None: page("a")}, {}),
        ({None: page("a", "b", watermark="done")}, {"page_size": 1}),
        (
            {None: page("a", next_cursor="two"), "two": page("b", watermark="done")},
            {"max_pages": 1},
        ),
        ({None: page("a", next_cursor="two", watermark="different")}, {}),
    ],
)
async def test_invalid_pagination_and_limits_fail_without_success_checkpoint(
    pages, config
):
    _, _, _, checkpoints, runner, service = setup(pages, **config)
    job_id = await service.start_sync("incremental")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await checkpoints.load("customer_sync")).last_success_at is None
    assert not (await service.get_sync_report(job_id)).complete


@pytest.mark.parametrize("external_id", [None, "", " ", "x" * 256])
async def test_missing_external_key_is_refused_and_bounded(external_id):
    _, _, _, checkpoints, runner, service = setup(
        {None: page(external_id, watermark="done")}
    )
    job_id = await service.start_sync("incremental")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await service.get_sync_report(job_id)).errors[
        0
    ].code == "missing_external_key"
    assert (await checkpoints.load("customer_sync")).last_successful_cursor is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"modes": []},
        {"modes": ["full", "full"]},
        {"modes": ["push"]},
        {"direction": "push"},
        {"page_size": 0},
        {"page_size": True},
        {"page_size": 1001},
        {"max_full_items": 0},
        {"max_full_items": 100001},
        {"max_pages": False},
        {"missing_policy": "delete"},
        {"conflict_policy": "target_wins"},
        {"execution": "inline"},
    ],
)
def test_definition_rejects_invalid_policies(kwargs):
    with pytest.raises(ValidationError):
        SyncDefinition(name="customer_sync", external_key="external_id", **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"completed": -1},
        {"completed": True},
        {"total": 2},
        {"completed": 3, "total": 2},
        {"percent": float("nan")},
    ],
)
def test_job_counter_progress_is_validated(kwargs):
    with pytest.raises(ValidationError):
        JobProgress(**kwargs)


async def test_checkpoint_cas_source_version_and_report_retention():
    checkpoints = InMemorySyncCheckpoint(max_reports=1)
    owner = uuid4()
    original = await checkpoints.claim("customer_sync", "1", owner)
    with pytest.raises(SyncBusy):
        await checkpoints.claim("customer_sync", "1", uuid4())
    with pytest.raises(SyncVersionConflict):
        await checkpoints.commit(original, owner=uuid4(), expected_version=0)
    updated = await checkpoints.commit(original, owner=owner, expected_version=0)
    with pytest.raises(SyncVersionConflict):
        await checkpoints.commit(original, owner=owner, expected_version=0)
    with pytest.raises(SyncVersionConflict):
        await checkpoints.commit(
            updated.model_copy(update={"source_version": "2"}),
            owner=owner,
            expected_version=1,
        )
    await checkpoints.release("customer_sync", uuid4())
    with pytest.raises(SyncBusy):
        await checkpoints.claim("customer_sync", "1", uuid4())
    await checkpoints.save_report(
        SyncReport(job_id=str(owner), sync_name="customer_sync")
    )
    with pytest.raises(ValueError, match="capacity"):
        await checkpoints.save_report(
            SyncReport(job_id=str(uuid4()), sync_name="customer_sync")
        )
    with pytest.raises(SyncBusy):
        await checkpoints.delete_report(owner)
    await checkpoints.release("customer_sync", owner)
    with pytest.raises(SyncVersionConflict):
        await checkpoints.claim("customer_sync", "2", owner)
    await checkpoints.delete_report(owner)
    assert await checkpoints.get_report(owner) is None


async def test_default_job_budget_and_queued_report_absence():
    _, _, _, checkpoints, runner, service = setup(modes=("full",))
    with pytest.raises(ValueError):
        await service.start_sync("incremental")
    job_id = await service.start_sync("full")
    assert (await service.get_sync_status(job_id)).request.max_attempts == 1
    with pytest.raises(SyncReportUnavailable):
        await service.get_sync_report(job_id)
    assert (await service.cancel_sync(job_id)).status is JobStatus.CANCELLED
    with pytest.raises(JobTransitionError):
        await runner.run(job_id)


async def test_target_reactivation_is_idempotent_and_copies_are_isolated():
    target = InMemorySyncTarget(Target, max_records=1)
    assert await seed(target, "a") == "created"
    assert await target.deactivate_missing("customer_sync", frozenset()) == 1
    assert await seed(target, "a") == "updated"
    assert await seed(target, "a") == "unchanged"
    value = await target.get_by_external_id("customer_sync", "a")
    value.fields["local"] = "mutated"
    assert (await target.get_by_external_id("customer_sync", "a")).fields[
        "local"
    ] == "local"
    with pytest.raises(ValueError, match="capacity"):
        await seed(target, "b")


async def test_mapper_may_not_hide_provider_or_secret_objects():
    class Unsafe(Target):
        secret: SecretStr = Field(default=SecretStr("never-show-this"), exclude=True)

    _, mapper, _, checkpoints, runner, service = setup()
    mapper.map = lambda source: SyncMapping(value=Unsafe(), owned_fields=("name",))
    job_id = await service.start_sync("incremental")
    result = await runner.run(job_id)
    assert result.status is JobStatus.FAILED
    report = await service.get_sync_report(job_id)
    assert report.errors[0].code == "mapping_failed"
    assert "never-show-this" not in report.model_dump_json() + result.model_dump_json()


async def test_full_sync_keeps_incremental_watermark():
    _, _, _, checkpoints, runner, service = setup({None: page("a", watermark="cursor")})
    first = await service.start_sync("incremental")
    await runner.run(first)
    second = await service.start_sync("full")
    await runner.run(second)
    assert (await checkpoints.load("customer_sync")).last_successful_cursor == "cursor"


async def test_empty_successful_full_deactivates_all_in_scope():
    _, _, target, _, runner, service = setup(
        {None: page()}, missing_policy="deactivate"
    )
    await seed(target, "absent")
    job_id = await service.start_sync("full")
    assert (await runner.run(job_id)).status is JobStatus.SUCCEEDED
    assert (await service.get_sync_report(job_id)).deactivated == 1


@pytest.mark.parametrize("outcome", [None, True, -1])
async def test_invalid_finalization_result_never_commits_success(outcome):
    class InvalidFinalize(InMemorySyncTarget[Target]):
        async def deactivate_missing(self, sync_name, seen_external_ids):
            return outcome

    _, _, _, checkpoints, runner, service = setup(
        target=InvalidFinalize(Target), missing_policy="deactivate"
    )
    job_id = await service.start_sync("full")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await service.get_sync_report(job_id)).errors[
        0
    ].code == "finalization_failed"
    assert (await checkpoints.load("customer_sync")).last_success_at is None


async def test_source_version_conflict_is_reported_before_reading_source():
    checkpoints = InMemorySyncCheckpoint()
    owner = uuid4()
    await checkpoints.claim("customer_sync", "1", owner)
    await checkpoints.release("customer_sync", owner)
    source, _, _, _, runner, service = setup(
        checkpoints=checkpoints, source_version="2"
    )
    job_id = await service.start_sync("full")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await service.get_sync_report(job_id)).errors[
        0
    ].code == "source_version_conflict"
    assert not source.calls


async def test_different_jobs_cannot_write_the_same_sync_scope_concurrently():
    source, _, _, _, runner, service = setup()
    entered, release = asyncio.Event(), asyncio.Event()
    original = source.fetch_page

    async def paused(**kwargs):
        entered.set()
        await release.wait()
        return await original(**kwargs)

    source.fetch_page = paused
    first, second = await asyncio.gather(
        service.start_sync("full"), service.start_sync("full")
    )
    task = asyncio.create_task(runner.run(first))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (await runner.run(second)).status is JobStatus.FAILED
        assert (await service.get_sync_report(second)).errors[0].code == "sync_busy"
    finally:
        release.set()
        await task
    assert (await service.get_sync_status(first)).status is JobStatus.SUCCEEDED
    assert len(source.calls) == 1


async def test_other_scopes_cannot_read_or_cancel_sync_jobs():
    _, _, _, checkpoints, runner, service = setup()
    job_id = await service.start_sync("full")
    other = SynchronizationService(
        SyncDefinition(name="other", external_key="external_id"),
        JobService(runner, runner._store),
        checkpoints,
    )
    with pytest.raises(SyncReportUnavailable):
        await other.get_sync_status(job_id)
    with pytest.raises(SyncReportUnavailable):
        await other.cancel_sync(job_id)
    await runner.run(job_id)
    with pytest.raises(SyncReportUnavailable):
        await other.get_sync_report(job_id)


async def test_report_publication_failure_does_not_claim_sync_success():
    class OnceFailingReport(InMemorySyncCheckpoint):
        failed = False

        async def save_report(self, report):
            if report.pages and not self.failed:
                self.failed = True
                raise OSError("report backend secret")
            await super().save_report(report)

    _, _, _, checkpoints, runner, service = setup(checkpoints=OnceFailingReport())
    job_id = await service.start_sync("incremental")
    assert (await runner.run(job_id)).status is JobStatus.FAILED
    assert (await service.get_sync_report(job_id)).errors[0].code == "execution_failed"
    checkpoint = await checkpoints.load("customer_sync")
    assert (
        checkpoint.last_successful_cursor == "done"
        and checkpoint.last_success_at is None
    )


def test_ownership_and_report_models_reject_invalid_data():
    for fields in [(), ("name", "name"), ("unknown",)]:
        with pytest.raises(ValidationError):
            SyncMapping(value=Target(), owned_fields=fields)
    with pytest.raises(ValidationError):
        SyncReport(job_id=str(uuid4()), sync_name="customer_sync", schema_version=True)
    with pytest.raises(ValidationError):
        SyncReport(job_id="not-a-job-id", sync_name="customer_sync")
    for value in (0, True):
        with pytest.raises(ValueError):
            InMemorySyncCheckpoint(max_reports=value)
        with pytest.raises(ValueError):
            InMemorySyncTarget(Target, max_records=value)


@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_duplicate_keys_in_a_page_fail_before_any_target_effect(mode):
    duplicates = SourcePage(
        items=(
            Source(external_id="a", name="first"),
            Source(external_id="a", name="second"),
        ),
        checkpoint_cursor="done",
    )
    _, _, target, checkpoints, runner, service = setup({None: duplicates})
    job_id = await service.start_sync(mode, max_attempts=2)
    for attempt in range(2):
        if attempt:
            await runner.retry(job_id)
        assert (await runner.run(job_id)).status is JobStatus.FAILED
        assert (await service.get_sync_report(job_id)).errors[0].code == "invalid_page"
        assert await target.get_by_external_id("customer_sync", "a") is None
        assert (await checkpoints.load("customer_sync")).last_successful_cursor is None


async def test_full_duplicate_keys_across_pages_cannot_oscillate_on_retry():
    _, _, target, _, runner, service = setup(
        {
            None: SourcePage(
                items=(Source(external_id="a", name="first"),), next_cursor="two"
            ),
            "two": SourcePage(items=(Source(external_id="a", name="second"),)),
        },
        missing_policy="deactivate",
    )
    await seed(target, "absent")
    job_id = await service.start_sync("full", max_attempts=2)
    for attempt in range(2):
        if attempt:
            await runner.retry(job_id)
        assert (await runner.run(job_id)).status is JobStatus.FAILED
        assert (await target.get_by_external_id("customer_sync", "a")).fields[
            "name"
        ] == "first"
        assert (await target.get_by_external_id("customer_sync", "absent")).active
    report = await service.get_sync_report(job_id)
    assert (report.created, report.unchanged, report.failed) == (0, 1, 1)
