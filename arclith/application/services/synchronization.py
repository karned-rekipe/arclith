"""Page-by-page pull reconciliation composed with the existing Job contract."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel

from arclith.application.services.job_service import JobService
from arclith.domain.errors.job import JobCancellationRequested
from arclith.domain.errors.synchronization import (
    SyncBusy,
    SyncReportUnavailable,
    SyncRunFailed,
    SyncVersionConflict,
)
from arclith.domain.models.job import JobId, JobProgress, JobRecord, JobRequest
from arclith.domain.models.synchronization import (
    SourcePage,
    SyncChange,
    SyncCheckpoint,
    SyncDefinition,
    SyncErrorCode,
    SyncItemError,
    SyncMapping,
    SyncMode,
    SyncReport,
    SyncRequest,
)
from arclith.domain.ports.outbound.job_runner import JobContext, JobHandler
from arclith.domain.ports.outbound.synchronization import (
    SyncCheckpointPort,
    SyncMapper,
    SyncSourcePort,
    SyncTargetPort,
)
from arclith.domain.services.job_payload import snapshot_payload


class _PageFailure(Exception):
    def __init__(self, code: SyncErrorCode, item: int | None = None) -> None:
        self.code = code
        self.item = item
        super().__init__(code)


@dataclass
class _Run:
    report: SyncReport
    checkpoint: SyncCheckpoint
    seen: set[str] = field(default_factory=set)
    cursors: set[str] = field(default_factory=set)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SyncJobHandler[SourceT: BaseModel, TargetT: BaseModel](
    JobHandler[SyncRequest, SyncReport]
):
    def __init__(
        self,
        definition: SyncDefinition,
        source: SyncSourcePort[SourceT],
        target: SyncTargetPort[TargetT],
        mapper: SyncMapper[SourceT, TargetT],
        checkpoints: SyncCheckpointPort,
        *,
        source_type: type[SourceT],
        target_type: type[TargetT],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.definition = SyncDefinition.model_validate(definition)
        self._source = source
        self._target = target
        self._mapper = mapper
        self._checkpoints = checkpoints
        self._source_type = source_type
        self._target_type = target_type
        self._clock = clock

    async def execute(self, request: SyncRequest, context: JobContext) -> SyncReport:
        self._validate_request(request)
        report = SyncReport(job_id=str(context.job_id), sync_name=self.definition.name)
        # Reserve report capacity before causing target effects.
        await self._checkpoints.save_report(report)
        checkpoint = await self._claim(context.job_id, report)
        run = _Run(report, checkpoint)
        try:
            await self._pages(run, request.mode, context)
            await context.cancellation.checkpoint()
            await self._finish(run, request.mode, context.job_id)
        except _PageFailure as failure:
            run.report = self._failed(run.report, failure.code, failure.item)
            raise SyncRunFailed(
                "Synchronization failed; inspect the bounded report"
            ) from None
        except JobCancellationRequested:
            run.report = self._failed(run.report, "cancelled")
            raise
        except asyncio.CancelledError:
            run.report = self._failed(run.report, "interrupted")
            raise
        except Exception:
            run.report = self._failed(run.report, "execution_failed")
            raise SyncRunFailed("Synchronization state publication failed") from None
        finally:
            try:
                await self._checkpoints.save_report(run.report)
            finally:
                await self._checkpoints.release(self.definition.name, context.job_id)
        return run.report

    def _validate_request(self, request: SyncRequest) -> None:
        if (
            request.sync_name != self.definition.name
            or request.source_version != self.definition.source_version
            or request.mode not in self.definition.modes
        ):
            raise ValueError("Sync request does not match this definition")

    async def _claim(self, job_id: JobId, report: SyncReport) -> SyncCheckpoint:
        try:
            return await self._checkpoints.claim(
                self.definition.name, self.definition.source_version, job_id
            )
        except SyncBusy:
            await self._checkpoints.save_report(self._failed(report, "sync_busy"))
            raise SyncRunFailed("Synchronization scope is already running") from None
        except SyncVersionConflict:
            await self._checkpoints.save_report(
                self._failed(report, "source_version_conflict")
            )
            raise SyncRunFailed("Synchronization source version changed") from None

    @staticmethod
    def _failed(
        report: SyncReport, code: SyncErrorCode, item: int | None = None
    ) -> SyncReport:
        error = SyncItemError(code=code, page=report.pages, item=item)
        return report.model_copy(
            update={
                "complete": False,
                "failed": report.failed + 1,
                "errors": (*report.errors, error)[:20],
            }
        )

    async def _pages(self, run: _Run, mode: SyncMode, context: JobContext) -> None:
        cursor = (
            run.checkpoint.last_successful_cursor if mode == "incremental" else None
        )
        if cursor is not None:
            run.cursors.add(cursor)
        while True:
            await context.cancellation.checkpoint()
            if run.report.pages >= self.definition.max_pages:
                raise _PageFailure("run_limit")
            page = await self._fetch(mode, cursor)
            self._validate_page(page, run, mode)
            for index, item in enumerate(page.items):
                await self._apply_item(run, item, index, mode)
            page_report = run.report.model_copy(update={"pages": run.report.pages + 1})
            watermark = (
                page.next_cursor
                if page.next_cursor is not None
                else page.checkpoint_cursor
            )
            updates: dict[str, object] = {"last_report": page_report}
            if mode == "incremental":
                updates["last_successful_cursor"] = (
                    watermark if watermark is not None else cursor
                )
            await self._commit(run, updates, context.job_id)
            run.report = page_report
            await self._checkpoints.save_report(run.report)
            await context.report_progress(JobProgress(completed=run.report.processed))
            if page.next_cursor is None:
                return
            cursor = page.next_cursor
            run.cursors.add(cursor)

    async def _fetch(self, mode: SyncMode, cursor: str | None) -> SourcePage[SourceT]:
        try:
            page = await self._source.fetch_page(
                mode=mode, cursor=cursor, limit=self.definition.page_size
            )
            if len(page.items) > self.definition.page_size:
                raise ValueError("Source page exceeds the configured page size")
            return SourcePage(
                items=tuple(
                    snapshot_payload(item, self._source_type) for item in page.items
                ),
                next_cursor=page.next_cursor,
                checkpoint_cursor=page.checkpoint_cursor,
            )
        except Exception:
            raise _PageFailure("source_failed") from None

    def _validate_page(
        self, page: SourcePage[SourceT], run: _Run, mode: SyncMode
    ) -> None:
        self._validate_keys(page, run, mode)
        if len(page.items) > self.definition.page_size:
            raise _PageFailure("invalid_page")
        if page.next_cursor is not None and page.next_cursor in run.cursors:
            raise _PageFailure("invalid_page")
        if (
            mode == "incremental"
            and page.next_cursor is None
            and page.items
            and page.checkpoint_cursor is None
        ):
            raise _PageFailure("invalid_page")
        if page.next_cursor is not None and page.checkpoint_cursor not in {
            None,
            page.next_cursor,
        }:
            raise _PageFailure("invalid_page")

    def _validate_keys(
        self, page: SourcePage[SourceT], run: _Run, mode: SyncMode
    ) -> None:
        keys: set[str] = set()
        for item in page.items:
            key: object = getattr(item, self.definition.external_key, None)
            if isinstance(key, str):
                if key in keys or (mode == "full" and key in run.seen):
                    raise _PageFailure("invalid_page")
                keys.add(key)

    async def _apply_item(
        self, run: _Run, item: SourceT, index: int, mode: SyncMode
    ) -> None:
        external_id = getattr(item, self.definition.external_key, None)
        if (
            type(external_id) is not str
            or not external_id.strip()
            or len(external_id) > 255
        ):
            raise _PageFailure("missing_external_key", index)
        if mode == "full":
            if (
                external_id not in run.seen
                and len(run.seen) >= self.definition.max_full_items
            ):
                raise _PageFailure("run_limit", index)
            run.seen.add(external_id)
        mapping = self._map(item, index)
        outcome = "skipped"
        if mapping is not None:
            outcome = await self._apply(external_id, mapping, index)
        run.report = run.report.model_copy(
            update={outcome: getattr(run.report, outcome) + 1}
        )

    def _map(self, item: SourceT, index: int) -> SyncMapping[TargetT] | None:
        try:
            mapping = self._mapper.map(snapshot_payload(item, self._source_type))
            if mapping is None:
                return None
            return SyncMapping(
                value=snapshot_payload(mapping.value, self._target_type),
                owned_fields=mapping.owned_fields,
            )
        except Exception:
            raise _PageFailure("mapping_failed", index) from None

    async def _apply(
        self, external_id: str, mapping: SyncMapping[TargetT], index: int
    ) -> str:
        try:
            outcome = await self._target.apply(
                SyncChange(
                    sync_name=self.definition.name,
                    external_id=external_id,
                    mapping=mapping,
                )
            )
            if outcome not in {"created", "updated", "unchanged"}:
                raise ValueError("Invalid target outcome")
            return outcome
        except Exception:
            raise _PageFailure("target_failed", index) from None

    async def _commit(
        self, run: _Run, updates: dict[str, object], owner: JobId
    ) -> None:
        try:
            checkpoint = SyncCheckpoint.model_validate(
                {
                    **run.checkpoint.model_dump(),
                    **updates,
                }
            )
            run.checkpoint = await self._checkpoints.commit(
                checkpoint,
                owner=owner,
                expected_version=run.checkpoint.version,
            )
        except Exception:
            raise _PageFailure("checkpoint_failed") from None

    async def _finish(self, run: _Run, mode: SyncMode, owner: JobId) -> None:
        if mode == "full" and self.definition.missing_policy == "deactivate":
            try:
                count = await self._target.deactivate_missing(
                    self.definition.name, frozenset(run.seen)
                )
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid deactivation count")
                run.report = run.report.model_copy(update={"deactivated": count})
            except Exception:
                raise _PageFailure("finalization_failed") from None
        completed = run.report.model_copy(update={"complete": True})
        await self._commit(
            run, {"last_success_at": self._clock(), "last_report": completed}, owner
        )
        run.report = completed


class SynchronizationService:
    def __init__(
        self,
        definition: SyncDefinition,
        jobs: JobService[SyncRequest, SyncReport],
        checkpoints: SyncCheckpointPort,
    ) -> None:
        self.definition = definition
        self._jobs = jobs
        self._checkpoints = checkpoints

    async def start_sync(
        self,
        mode: SyncMode,
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 1,
    ) -> JobId:
        if mode not in self.definition.modes:
            raise ValueError("Sync mode is not enabled")
        return await self._jobs.submit(
            JobRequest(
                payload=SyncRequest(
                    sync_name=self.definition.name,
                    source_version=self.definition.source_version,
                    mode=mode,
                ),
                idempotency_key=idempotency_key,
                max_attempts=max_attempts,
            )
        )

    async def get_sync_status(
        self, job_id: JobId
    ) -> JobRecord[SyncRequest, SyncReport]:
        record = await self._jobs.get_status(job_id)
        if record.request.payload.sync_name != self.definition.name:
            raise SyncReportUnavailable("Job belongs to another synchronization")
        return record

    async def cancel_sync(self, job_id: JobId) -> JobRecord[SyncRequest, SyncReport]:
        await self.get_sync_status(job_id)
        return await self._jobs.cancel(job_id)

    async def get_sync_report(self, job_id: JobId) -> SyncReport:
        report = await self._checkpoints.get_report(job_id)
        if report is None or report.sync_name != self.definition.name:
            raise SyncReportUnavailable(
                "No synchronization attempt report is available"
            )
        return report
