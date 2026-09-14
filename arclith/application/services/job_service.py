"""Provider-neutral application operations for one typed job definition."""

from pydantic import BaseModel

from arclith.domain.errors.job import JobNotFound, JobResultUnavailable
from arclith.domain.models.job import JobId, JobRecord, JobRequest, JobResult, JobStatus
from arclith.domain.ports.outbound.job_runner import JobRunnerPort
from arclith.domain.ports.outbound.job_store import JobStorePort


class JobService[RequestT: BaseModel, ResultT: BaseModel]:
    def __init__(
        self,
        runner: JobRunnerPort[RequestT, ResultT],
        store: JobStorePort[RequestT, ResultT],
    ) -> None:
        self._runner = runner
        self._store = store

    async def submit(self, request: JobRequest[RequestT]) -> JobId:
        return await self._runner.submit(request)

    async def get_status(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        record = await self._store.get(job_id)
        if record is None:
            raise JobNotFound("Job not found")
        return record

    async def cancel(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        return await self._runner.cancel(job_id)

    async def retry(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        return await self._runner.retry(job_id)

    async def get_result(self, job_id: JobId) -> JobResult[ResultT]:
        record = await self.get_status(job_id)
        if record.status is not JobStatus.SUCCEEDED or record.result is None:
            raise JobResultUnavailable("Job has not succeeded")
        return record.result
