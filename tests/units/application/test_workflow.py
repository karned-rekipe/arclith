import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from arclith.adapters.outbound.memory.workflow_runner import InMemoryWorkflowRunner
from arclith.adapters.outbound.memory.workflow_store import InMemoryWorkflowStore
from arclith.application.services.workflow_service import WorkflowService
from arclith.domain.errors.job import JobCancellationRequested
from arclith.domain.errors.workflow import (
    WorkflowBusy,
    WorkflowDefinitionConflict,
    WorkflowIdempotencyConflict,
    WorkflowNotFound,
    WorkflowResultUnavailable,
    WorkflowTransitionError,
    WorkflowVersionConflict,
)
from arclith.domain.models.workflow import (
    WorkflowDefinition,
    WorkflowFailure,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepRecord,
    WorkflowStepStatus,
)
from arclith.domain.ports.outbound.workflow_runner import (
    WorkflowResultMapper,
    WorkflowStep,
)
from arclith.domain.services.workflow_lifecycle import (
    AcknowledgeWorkflowCancellation,
    BeginWorkflowStep,
    CancelWorkflow,
    CommitWorkflowStep,
    CompleteWorkflow,
    FailWorkflow,
    StartWorkflow,
    transition_workflow,
)


class Context(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trace: tuple[str, ...] = ()
    reference: str = "document-1"


class Result(BaseModel):
    trace: tuple[str, ...]


class Step(WorkflowStep[Context]):
    def __init__(self, name, *, fail=0):
        self._name = name
        self.fail = fail
        self.calls = []

    @property
    def name(self):
        return self._name

    async def execute(self, context, *, execution):
        self.calls.append((context, execution))
        if len(self.calls) <= self.fail:
            raise RuntimeError("business-secret-not-for-public-errors")
        return Context(trace=(*context.trace, self.name), reference=context.reference)


class Mapper(WorkflowResultMapper[Context, Result]):
    def build_result(self, context):
        return Result(trace=context.trace)


def definition(*, attempts=2, version=1):
    return WorkflowDefinition(
        name="publication",
        version=version,
        context="Context",
        result="Result",
        steps=tuple(
            WorkflowStepDefinition(name=name, max_attempts=attempts)
            for name in ("validate", "publish", "notify")
        ),
    )


def setup(*, steps=None, store=None, mapper=None, config=None):
    config = config or definition()
    store = store or InMemoryWorkflowStore(Context, Result)
    steps = steps or [Step(step.name) for step in config.steps]
    runner = InMemoryWorkflowRunner(
        config,
        store,
        steps,
        mapper or Mapper(),
        context_type=Context,
        result_type=Result,
    )
    service = WorkflowService(config, runner, store)
    return steps, store, runner, service


async def test_order_checkpoints_result_and_bounded_events():
    steps, store, runner, service = setup()
    checkpoints = []
    original = store.change

    async def observe(workflow_id, change, **kwargs):
        record = await original(workflow_id, change, **kwargs)
        if isinstance(change, CommitWorkflowStep):
            checkpoints.append((record.checkpoint, record.context.trace))
        return record

    store.change = observe
    workflow_id = await service.start(Context())
    assert (await service.get_status(workflow_id)).status is WorkflowStatus.PENDING
    with pytest.raises(WorkflowResultUnavailable):
        await service.get_result(workflow_id)
    record = await runner.run(workflow_id)
    assert record.status is WorkflowStatus.COMPLETED
    assert checkpoints == [
        (1, ("validate",)),
        (2, ("validate", "publish")),
        (3, ("validate", "publish", "notify")),
    ]
    assert (await service.get_result(workflow_id)).trace == (
        "validate",
        "publish",
        "notify",
    )
    assert record.progress.completed == record.progress.total == 3
    assert record.progress.percent is None
    assert [e.kind for e in record.events] == [
        "started",
        "step_started",
        "step_succeeded",
        "step_started",
        "step_succeeded",
        "step_started",
        "step_succeeded",
        "completed",
    ]
    assert [e.sequence for e in record.events] == list(range(2, 10))
    assert all(step.calls[0][1].attempt == 1 for step in steps)
    with pytest.raises(WorkflowTransitionError):
        await runner.run(workflow_id)
    with pytest.raises(WorkflowTransitionError):
        await service.resume(workflow_id)


async def test_explicit_resume_preserves_successful_steps_and_execution_key():
    steps = [Step("validate"), Step("publish", fail=1), Step("notify")]
    _, store, runner, service = setup(steps=steps)
    workflow_id = await service.start(Context())
    failed = await runner.run(workflow_id)
    assert failed.status is WorkflowStatus.FAILED and failed.checkpoint == 1
    assert failed.context.trace == ("validate",)
    assert failed.steps[1].error.code == "step_failed"
    assert "business-secret" not in failed.model_dump_json()
    assert len(steps[2].calls) == 0
    assert (await service.resume(workflow_id)).status is WorkflowStatus.COMPLETED
    assert [len(step.calls) for step in steps] == [1, 2, 1]
    first, second = [call[1] for call in steps[1].calls]
    assert first.execution_key == second.execution_key
    assert (first.attempt, second.attempt) == (1, 2)


@pytest.mark.parametrize("after_commit", [False, True])
async def test_lost_checkpoint_response_and_unconfirmed_effects(after_commit):
    steps, store, runner, service = setup()
    effects = set()
    business_calls = []
    original_step = steps[1].execute

    async def idempotent(context, *, execution):
        business_calls.append(execution.execution_key)
        effects.add(execution.execution_key)
        return await original_step(context, execution=execution)

    steps[1].execute = idempotent
    original = store.change
    fail_once = True

    async def fail_checkpoint(workflow_id, change, **kwargs):
        nonlocal fail_once
        if (
            isinstance(change, CommitWorkflowStep)
            and change.context.trace == ("validate", "publish")
            and fail_once
        ):
            fail_once = False
            if after_commit:
                await original(workflow_id, change, **kwargs)
            raise OSError("lost checkpoint response")
        return await original(workflow_id, change, **kwargs)

    store.change = fail_checkpoint
    workflow_id = await service.start(Context())
    with pytest.raises(OSError):
        await runner.run(workflow_id)
    stored = await store.get(workflow_id)
    assert stored.status is WorkflowStatus.RUNNING
    assert stored.checkpoint == (2 if after_commit else 1)
    # A fresh runner over the same store recovers only from persisted state.
    _, _, restarted, _ = setup(steps=steps, store=store)
    completed = await restarted.resume(workflow_id)
    assert completed.status is WorkflowStatus.COMPLETED
    assert len(steps[0].calls) == 1
    assert len(business_calls) == (1 if after_commit else 2)
    assert len(effects) == 1


@pytest.mark.parametrize("attempts", [1, 2])
async def test_retry_budget_is_persisted(attempts):
    steps = [Step("validate", fail=10), Step("publish"), Step("notify")]
    _, store, runner, service = setup(steps=steps, config=definition(attempts=attempts))
    workflow_id = await service.start(Context())
    await runner.run(workflow_id)
    if attempts == 2:
        assert (await service.resume(workflow_id)).status is WorkflowStatus.FAILED
    before = await store.get(workflow_id)
    with pytest.raises(WorkflowTransitionError, match="max_attempts"):
        await service.resume(workflow_id)
    assert await store.get(workflow_id) == before
    assert len(steps[0].calls) == attempts


async def test_concurrent_runners_and_resume_do_not_duplicate_a_step():
    steps, store, runner, service = setup()
    entered, release = asyncio.Event(), asyncio.Event()
    original = steps[0].execute

    async def paused(context, *, execution):
        entered.set()
        await release.wait()
        return await original(context, execution=execution)

    steps[0].execute = paused
    _, _, other, _ = setup(steps=steps, store=store)
    workflow_id = await service.start(Context())
    task = asyncio.create_task(runner.run(workflow_id))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        for method in (other.run, other.resume):
            with pytest.raises(WorkflowBusy):
                await method(workflow_id)
    finally:
        release.set()
        await task
    assert [len(step.calls) for step in steps] == [1, 1, 1]


async def test_cancel_pending_and_resume_cancelled_refused():
    steps, _, runner, service = setup()
    workflow_id = await service.start(Context())
    cancelled = await service.cancel(workflow_id)
    assert cancelled.status is WorkflowStatus.CANCELLED
    assert await service.cancel(workflow_id) == cancelled
    for method in (runner.run, service.resume):
        with pytest.raises(WorkflowTransitionError):
            await method(workflow_id)
    assert not any(step.calls for step in steps)


@pytest.mark.parametrize("checkpoint_inside", [False, True])
async def test_cancel_running_finishes_only_current_step(checkpoint_inside):
    steps, _, runner, service = setup()
    entered, release = asyncio.Event(), asyncio.Event()
    original = steps[0].execute

    async def paused(context, *, execution):
        entered.set()
        await release.wait()
        if checkpoint_inside:
            await execution.cancellation.checkpoint()
        return await original(context, execution=execution)

    steps[0].execute = paused
    workflow_id = await service.start(Context())
    task = asyncio.create_task(runner.run(workflow_id))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        assert (await service.cancel(workflow_id)).cancellation_requested
    finally:
        release.set()
        record = await task
    assert record.status is WorkflowStatus.CANCELLED
    assert record.checkpoint == (0 if checkpoint_inside else 1)
    assert not steps[1].calls


async def test_owner_cancellation_is_collected_and_releases_claim():
    steps, store, runner, service = setup()
    entered = asyncio.Event()
    original = steps[0].execute

    async def wait(context, *, execution):
        entered.set()
        await asyncio.Event().wait()

    steps[0].execute = wait
    workflow_id = await service.start(Context())
    task = asyncio.create_task(runner.run(workflow_id))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    failed = await store.get(workflow_id)
    assert failed.error.code == "execution_interrupted"
    assert failed.steps[0].attempts == 1 and failed.checkpoint == 0
    steps[0].execute = original
    assert (await service.resume(workflow_id)).status is WorkflowStatus.COMPLETED


async def test_definition_version_order_and_schema_drift_refused_without_changes():
    _, store, runner, service = setup()
    workflow_id = await service.start(Context())
    original = await store.get(workflow_id)
    changed = definition(version=2)
    _, _, other, other_service = setup(store=store, config=changed)
    for method in (
        other.run,
        other.resume,
        other_service.get_status,
        other_service.cancel,
    ):
        with pytest.raises(WorkflowDefinitionConflict):
            await method(workflow_id)
    altered = definition().model_copy(
        update={"steps": tuple(reversed(definition().steps))}
    )
    _, _, reordered, _ = setup(store=store, config=altered)
    with pytest.raises(WorkflowDefinitionConflict):
        await reordered.run(workflow_id)
    changed_context = type(
        "Context",
        (Context,),
        {"__annotations__": {"extra_field": str}, "extra_field": "value"},
    )
    schema_runner = InMemoryWorkflowRunner(
        definition(),
        store,
        [Step(s.name) for s in definition().steps],
        Mapper(),
        context_type=changed_context,
        result_type=Result,
    )
    with pytest.raises(WorkflowDefinitionConflict):
        await schema_runner.run(workflow_id)
    assert await store.get(workflow_id) == original
    assert (await runner.run(workflow_id)).status is WorkflowStatus.COMPLETED


async def test_concurrent_submission_dedup_conflict_and_detached_snapshots():
    _, store, _, service = setup()
    ids = await asyncio.gather(
        *(service.start(Context(), idempotency_key="same") for _ in range(20))
    )
    assert len(set(ids)) == 1
    with pytest.raises(WorkflowIdempotencyConflict):
        await service.start(Context(reference="different"), idempotency_key="same")
    record = await store.get(ids[0])
    object.__setattr__(record.context, "reference", "mutated")
    assert (await store.get(ids[0])).context.reference == "document-1"


@pytest.mark.parametrize("value", ["", "x" * 256, " padded", "new\nline", 1])
async def test_invalid_idempotency_keys(value):
    _, _, _, service = setup()
    with pytest.raises((ValueError, TypeError)):
        await service.start(Context(), idempotency_key=value)


@pytest.mark.parametrize(
    "kind", ["secret", "hidden", "oversize", "deep", "object", "nan"]
)
async def test_unsafe_context_rejected_even_when_serializers_hide_it(kind):
    class UnsafeContext(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        value: object = Field(exclude=kind == "hidden")

    value = (
        SecretStr("sensitive")
        if kind in {"secret", "hidden"}
        else "a" * 65537
        if kind == "oversize"
        else object()
        if kind == "object"
        else float("nan")
        if kind == "nan"
        else []
    )
    if kind == "deep":
        for _ in range(35):
            value = [value]
    store = InMemoryWorkflowStore(UnsafeContext, Result)
    config = definition().model_copy(update={"context": "UnsafeContext"})
    with pytest.raises(ValueError):
        await store.create(config, UnsafeContext(value=value))
    assert not store._records


@pytest.mark.parametrize("kind", ["wrong", "oversize", "unimplemented", "false_cancel"])
async def test_bad_step_output_and_errors_are_bounded(kind):
    steps, _, runner, service = setup()

    async def invalid(context, *, execution):
        if kind == "unimplemented":
            raise NotImplementedError("secret")
        if kind == "false_cancel":
            raise JobCancellationRequested("secret")
        return Result(trace=()) if kind == "wrong" else Context(reference="s" * 70000)

    steps[0].execute = invalid
    record = await runner.run(await service.start(Context()))
    assert record.status is WorkflowStatus.FAILED
    assert record.checkpoint == 0
    assert record.error.code == (
        "step_not_implemented" if kind == "unimplemented" else "step_failed"
    )
    assert "secret" not in record.model_dump_json()


async def test_result_failure_can_resume_without_replaying_confirmed_steps():
    mapper = Mapper()
    original = mapper.build_result
    mapper.build_result = lambda context: Context()
    steps, _, runner, service = setup(mapper=mapper)
    workflow_id = await service.start(Context())
    failed = await runner.run(workflow_id)
    assert failed.error.code == "result_failed" and failed.checkpoint == 3
    mapper.build_result = original
    assert (await service.resume(workflow_id)).status is WorkflowStatus.COMPLETED
    assert [len(step.calls) for step in steps] == [1, 1, 1]


async def test_cas_ownership_and_store_capacity():
    store = InMemoryWorkflowStore(Context, Result, max_instances=1)
    _, _, runner, service = setup(store=store)
    workflow_id = await service.start(Context(), idempotency_key="first")
    with pytest.raises(WorkflowTransitionError, match="capacity"):
        await service.start(Context())
    with pytest.raises(WorkflowTransitionError):
        await store.delete_terminal(workflow_id)
    with pytest.raises(WorkflowBusy):
        await store.change(workflow_id, StartWorkflow(), expected_version=1)
    owner = uuid4()
    await store.claim(workflow_id, owner)
    with pytest.raises(WorkflowBusy):
        await store.release(workflow_id, uuid4())
    with pytest.raises(WorkflowVersionConflict):
        await store.change(
            workflow_id, StartWorkflow(), expected_version=2, owner=owner
        )
    await store.release(workflow_id, owner)
    await runner.run(workflow_id)
    await store.delete_terminal(workflow_id)
    assert await store.get(workflow_id) is None
    assert await service.start(Context(), idempotency_key="first") != workflow_id


@pytest.mark.parametrize(
    "operation",
    ["status", "result", "cancel", "run", "resume", "claim", "change", "delete"],
)
async def test_missing_workflow(operation):
    _, store, runner, service = setup()
    methods = {
        "status": service.get_status,
        "result": service.get_result,
        "cancel": service.cancel,
        "run": runner.run,
        "resume": service.resume,
        "claim": lambda i: store.claim(i, uuid4()),
        "change": lambda i: store.change(i, CancelWorkflow(), expected_version=1),
        "delete": store.delete_terminal,
    }
    with pytest.raises(WorkflowNotFound):
        await methods[operation](uuid4())


@pytest.mark.parametrize(
    "patch",
    [
        {"steps": ()},
        {"steps": (WorkflowStepDefinition(name="a"),) * 101},
        {"steps": (WorkflowStepDefinition(name="a"),) * 2},
        {"version": True},
        {"name": "../unsafe"},
        {"context": "Result"},
        {"schema_version": True},
    ],
)
def test_definition_validation(patch):
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({**definition().model_dump(), **patch})


def test_injected_names_models_and_limits_validated():
    with pytest.raises(ValueError, match="order"):
        setup(steps=[Step("different")])
    with pytest.raises(ValueError, match="names"):
        setup(config=definition().model_copy(update={"context": "OtherContext"}))
    with pytest.raises(ValueError):
        InMemoryWorkflowStore(Context, Result, max_instances=True)


async def test_cancellation_racing_step_start_prevents_business_call():
    steps, store, runner, service = setup()
    original = store.change
    first = True

    async def race(workflow_id, change, **kwargs):
        nonlocal first
        if isinstance(change, BeginWorkflowStep) and first:
            first = False
            await service.cancel(workflow_id)
        return await original(workflow_id, change, **kwargs)

    store.change = race
    record = await runner.run(await service.start(Context()))
    assert record.status is WorkflowStatus.CANCELLED
    assert not any(step.calls for step in steps)


async def test_cancel_racing_result_publication_wins():
    _, store, runner, service = setup()
    original = store.change
    first = True

    async def race(workflow_id, change, **kwargs):
        nonlocal first
        if isinstance(change, CompleteWorkflow) and first:
            first = False
            await service.cancel(workflow_id)
        return await original(workflow_id, change, **kwargs)

    store.change = race
    record = await runner.run(await service.start(Context()))
    assert record.status is WorkflowStatus.CANCELLED and record.result is None
    assert record.checkpoint == 3


async def test_events_bounded_across_many_explicit_attempts():
    config = definition(attempts=100)
    steps = [Step("validate", fail=99), Step("publish"), Step("notify")]
    _, _, runner, service = setup(steps=steps, config=config)
    workflow_id = await service.start(Context())
    await runner.run(workflow_id)
    for _ in range(99):
        record = await service.resume(workflow_id)
    assert record.status is WorkflowStatus.COMPLETED
    assert len(record.events) == 200
    assert record.events[-1].sequence == record.version
    assert record.events[0].sequence > 1


async def test_lifecycle_rejects_invalid_transitions_and_clock():
    _, store, _, service = setup()
    record = await store.get(await service.start(Context()))
    for change in (
        BeginWorkflowStep(),
        CommitWorkflowStep(Context()),
        CompleteWorkflow(Result(trace=())),
        FailWorkflow(WorkflowFailure(code="step_failed")),
        AcknowledgeWorkflowCancellation(),
        StartWorkflow(resume=True),
    ):
        with pytest.raises(WorkflowTransitionError):
            transition_workflow(record, change, now=record.updated_at)
    with pytest.raises(ValueError):
        transition_workflow(record, StartWorkflow(), now=datetime.now())
    with pytest.raises(ValueError):
        transition_workflow(
            record, StartWorkflow(), now=record.created_at - timedelta(seconds=1)
        )
    running = transition_workflow(record, StartWorkflow(), now=record.updated_at)
    with pytest.raises(WorkflowTransitionError):
        transition_workflow(
            running, CompleteWorkflow(Result(trace=())), now=running.updated_at
        )
    with pytest.raises(WorkflowTransitionError):
        transition_workflow(
            running, AcknowledgeWorkflowCancellation(), now=running.updated_at
        )
    started = transition_workflow(running, BeginWorkflowStep(), now=running.updated_at)
    with pytest.raises(WorkflowTransitionError):
        transition_workflow(started, BeginWorkflowStep(), now=started.updated_at)


@pytest.mark.parametrize(
    "case",
    [
        "backwards_clock",
        "missing_terminal_time",
        "wrong_terminal_time",
        "unexpected_result",
        "missing_error",
        "incomplete_completion",
        "unrequested_cancel",
        "pending_with_attempt",
        "step_count",
        "step_name",
        "attempt_budget",
        "out_of_order",
        "missing_checkpoint",
    ],
)
async def test_invalid_persisted_instance_is_rejected(case):
    _, store, _, service = setup()
    record = await store.get(await service.start(Context()))
    now = record.updated_at
    data = {name: getattr(record, name) for name in type(record).model_fields}
    step = WorkflowStepRecord(
        name="validate", status=WorkflowStepStatus.RUNNING, attempts=1
    )
    patches = {
        "backwards_clock": {"updated_at": now - timedelta(seconds=1)},
        "missing_terminal_time": {
            "status": WorkflowStatus.FAILED,
            "error": WorkflowFailure(code="step_failed"),
        },
        "wrong_terminal_time": {
            "status": WorkflowStatus.CANCELLED,
            "cancellation_requested": True,
            "finished_at": now - timedelta(seconds=1),
        },
        "unexpected_result": {"result": Result(trace=())},
        "missing_error": {"status": WorkflowStatus.FAILED, "finished_at": now},
        "incomplete_completion": {
            "status": WorkflowStatus.COMPLETED,
            "finished_at": now,
            "result": Result(trace=()),
        },
        "unrequested_cancel": {"status": WorkflowStatus.CANCELLED, "finished_at": now},
        "pending_with_attempt": {"steps": (step, *record.steps[1:])},
        "step_count": {"checkpoint": 4},
        "step_name": {"steps": (WorkflowStepRecord(name="wrong"), *record.steps[1:])},
        "attempt_budget": {
            "steps": (step.model_copy(update={"attempts": 3}), *record.steps[1:])
        },
        "out_of_order": {
            "steps": (
                record.steps[0],
                WorkflowStepRecord(
                    name="publish", status=WorkflowStepStatus.SUCCEEDED, attempts=1
                ),
                record.steps[2],
            )
        },
        "missing_checkpoint": {
            "steps": (
                step.model_copy(update={"status": WorkflowStepStatus.SUCCEEDED}),
                *record.steps[1:],
            )
        },
    }
    with pytest.raises(ValidationError):
        type(record).model_validate({**data, **patches[case]})


@pytest.mark.parametrize(
    "data",
    [
        {"name": "step", "attempts": 1},
        {"name": "step", "status": "failed", "attempts": 1},
    ],
)
def test_invalid_step_snapshot_is_rejected(data):
    with pytest.raises(ValidationError):
        WorkflowStepRecord.model_validate(data)


async def test_version_races_are_bounded_and_claim_released():
    _, store, runner, service = setup()
    workflow_id = await service.start(Context())
    original = store.change
    calls = 0

    async def race(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise WorkflowVersionConflict("race")

    store.change = race
    for operation in (runner.run, service.cancel):
        with pytest.raises(WorkflowVersionConflict, match="changed repeatedly"):
            await operation(workflow_id)
    assert calls == 16
    store.change = original
    assert (await runner.run(workflow_id)).status is WorkflowStatus.COMPLETED


@pytest.mark.parametrize("after_commit", [False, True])
async def test_result_publication_failure_or_cancellation_preserves_checkpoints(
    after_commit,
):
    steps, store, runner, service = setup()
    original = store.change
    first = True

    async def fail_publication(workflow_id, change, **kwargs):
        nonlocal first
        if isinstance(change, CompleteWorkflow) and first:
            first = False
            if after_commit:
                await original(workflow_id, change, **kwargs)
                raise asyncio.CancelledError
            raise OSError("uncertain result publication")
        return await original(workflow_id, change, **kwargs)

    store.change = fail_publication
    workflow_id = await service.start(Context())
    with pytest.raises(asyncio.CancelledError if after_commit else OSError):
        await runner.run(workflow_id)
    record = await store.get(workflow_id)
    assert record.checkpoint == 3
    if after_commit:
        assert record.status is WorkflowStatus.COMPLETED
    else:
        assert (await service.resume(workflow_id)).status is WorkflowStatus.COMPLETED
    assert all(len(step.calls) == 1 for step in steps)


async def test_last_step_cancellation_before_projection():
    steps, _, runner, service = setup()
    workflow_id = await service.start(Context())
    original = steps[-1].execute

    async def request_cancel(context, *, execution):
        await service.cancel(workflow_id)
        return await original(context, execution=execution)

    steps[-1].execute = request_cancel
    record = await runner.run(workflow_id)
    assert record.status is WorkflowStatus.CANCELLED and record.checkpoint == 3
    assert record.result is None


async def test_store_rejects_unsafe_checkpoint_and_invalid_version():
    _, store, _, service = setup()
    workflow_id = await service.start(Context())
    owner = uuid4()
    await store.claim(workflow_id, owner)
    with pytest.raises(ValueError):
        await store.change(
            workflow_id, StartWorkflow(), expected_version=True, owner=owner
        )
    await store.change(workflow_id, StartWorkflow(), expected_version=1, owner=owner)
    record = await store.change(
        workflow_id, BeginWorkflowStep(), expected_version=2, owner=owner
    )
    with pytest.raises(ValueError):
        await store.change(
            workflow_id,
            CommitWorkflowStep(Context(reference="x" * 70000)),
            expected_version=record.version,
            owner=owner,
        )
    assert await store.get(workflow_id) == record
    await store.release(workflow_id, owner)
