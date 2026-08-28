from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from arclith.adapters.inbound.langgraph_runtime.coordination import RunBusyError
from arclith.adapters.inbound.langgraph_runtime.catalog import ThreadAlreadyExistsError
from arclith.adapters.inbound.langgraph_runtime.runtime import (
    AssistantNotFoundError,
    LangGraphRuntime,
    RunCancelledError,
    RunNotFoundError,
    RunRequest,
    RuntimeStorageError,
    ThreadNotFoundError,
)

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"description": "Thread, run or assistant not found"}
}
_RUN_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "Thread or assistant not found"},
    409: {"description": "Thread busy or run cancelled"},
    500: {"description": "Graph execution failed"},
    503: {"description": "Runtime storage unavailable"},
}


class ThreadCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thread_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    if_exists: Literal["raise", "do_nothing"] | None = None


class ThreadSearchPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metadata: dict[str, Any] | None = None
    status: str | None = None
    limit: int = Field(default=10, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class ThreadHistoryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    limit: int = Field(default=10, ge=1, le=1000)


class RunPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assistant_id: str = Field(min_length=1, max_length=200)
    input: Any = None
    command: Any = None
    config: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_id: str | None = None
    stream_mode: str | list[str] | None = None
    on_disconnect: Literal["cancel", "continue"] = "cancel"
    multitask_strategy: Literal["reject"] = "reject"

    def as_runtime_request(self) -> RunRequest:
        return RunRequest(
            assistant_id=self.assistant_id,
            input=self.input,
            command=self.command,
            config=self.config,
            checkpoint=self.checkpoint,
            checkpoint_id=self.checkpoint_id,
            stream_mode=self.stream_mode,
            on_disconnect=self.on_disconnect,
            multitask_strategy=self.multitask_strategy,
        )


def create_langgraph_runtime_app(runtime: LangGraphRuntime) -> FastAPI:
    app = FastAPI(
        title="Arclith Open Source LangGraph Runtime",
        version="1.0.0",
    )
    app.state.langgraph_runtime = runtime
    _register_exception_handlers(app)

    @app.get(
        "/info",
        status_code=status.HTTP_200_OK,
        responses={503: {"description": "Runtime unavailable"}},
    )
    async def info() -> dict[str, Any]:
        return {
            "version": "arclith-open-source",
            "flags": {
                "assistants": True,
                "crons": False,
                "langsmith": False,
            },
            "host": {"kind": "self-hosted-open-source"},
        }

    @app.get(
        "/health",
        status_code=status.HTTP_200_OK,
        responses={503: {"description": "Runtime unavailable"}},
    )
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/ready",
        status_code=status.HTTP_200_OK,
        responses={503: {"description": "Runtime storage unavailable"}},
    )
    async def ready() -> dict[str, str]:
        if not await runtime.ready():
            raise RuntimeStorageError("Runtime storage is not ready")
        return {"status": "ready"}

    @app.post(
        "/assistants/search",
        status_code=status.HTTP_200_OK,
        responses={503: {"description": "Runtime unavailable"}},
    )
    async def search_assistants() -> list[dict[str, Any]]:
        return runtime.assistants()

    @app.get(
        "/assistants/{assistant_id}",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def get_assistant(assistant_id: str) -> dict[str, Any]:
        return runtime.assistant(assistant_id)

    @app.post(
        "/threads/search",
        status_code=status.HTTP_200_OK,
        responses={503: {"description": "Runtime storage unavailable"}},
    )
    async def search_threads(payload: ThreadSearchPayload) -> list[dict[str, Any]]:
        records = await runtime.search_threads(
            metadata=payload.metadata,
            status=payload.status,
            limit=payload.limit,
            offset=payload.offset,
        )
        return [record.as_api_dict() for record in records]

    @app.post(
        "/threads",
        status_code=status.HTTP_200_OK,
        responses={
            409: {"description": "Thread already exists"},
            503: {"description": "Runtime storage unavailable"},
        },
    )
    async def create_thread(payload: ThreadCreatePayload) -> dict[str, Any]:
        record = await runtime.create_thread(
            thread_id=str(payload.thread_id) if payload.thread_id else None,
            metadata=payload.metadata,
            if_exists=payload.if_exists,
        )
        return record.as_api_dict()

    @app.get(
        "/threads/{thread_id}",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def get_thread(thread_id: UUID) -> dict[str, Any]:
        return (await runtime.get_thread(str(thread_id))).as_api_dict()

    @app.delete(
        "/threads/{thread_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_NOT_FOUND,
    )
    async def delete_thread(thread_id: UUID) -> Response:
        await runtime.delete_thread(str(thread_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/threads/{thread_id}/state",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def get_thread_state(thread_id: UUID) -> dict[str, Any]:
        return await runtime.state(str(thread_id))

    @app.post(
        "/threads/{thread_id}/history",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def get_thread_history(
        thread_id: UUID,
        payload: ThreadHistoryPayload,
    ) -> list[dict[str, Any]]:
        return await runtime.history(str(thread_id), limit=payload.limit)

    @app.post(
        "/threads/{thread_id}/runs/wait",
        status_code=status.HTTP_200_OK,
        responses=_RUN_ERRORS,
    )
    async def wait_for_run(thread_id: UUID, payload: RunPayload) -> Any:
        return await runtime.wait(
            str(thread_id),
            payload.as_runtime_request(),
        )

    @app.post(
        "/threads/{thread_id}/runs/stream",
        status_code=status.HTTP_200_OK,
        responses=_RUN_ERRORS,
    )
    async def stream_run(thread_id: UUID, payload: RunPayload) -> StreamingResponse:
        resolved_thread = str(thread_id)
        await runtime.get_thread(resolved_thread)
        runtime.assistant(payload.assistant_id)
        return StreamingResponse(
            runtime.stream(resolved_thread, payload.as_runtime_request()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get(
        "/threads/{thread_id}/runs",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def list_runs(
        thread_id: UUID,
        limit: int = Query(default=10, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        run_status: str | None = Query(default=None, alias="status"),
    ) -> list[dict[str, Any]]:
        runs = await runtime.list_runs(
            str(thread_id),
            status=run_status,
            limit=limit,
            offset=offset,
        )
        return [run.as_api_dict() for run in runs]

    @app.get(
        "/threads/{thread_id}/runs/{run_id}",
        status_code=status.HTTP_200_OK,
        responses=_NOT_FOUND,
    )
    async def get_run(thread_id: UUID, run_id: UUID) -> dict[str, Any]:
        return (await runtime.get_run(str(thread_id), str(run_id))).as_api_dict()

    @app.post(
        "/threads/{thread_id}/runs/{run_id}/cancel",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_NOT_FOUND,
    )
    async def cancel_run(thread_id: UUID, run_id: UUID) -> Response:
        await runtime.cancel_run(str(thread_id), str(run_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ThreadNotFoundError)
    @app.exception_handler(RunNotFoundError)
    @app.exception_handler(AssistantNotFoundError)
    async def not_found(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(RunBusyError)
    @app.exception_handler(RunCancelledError)
    @app.exception_handler(ThreadAlreadyExistsError)
    async def conflict(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RuntimeStorageError)
    async def unavailable(
        _request: Request,
        _error: RuntimeStorageError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "The LangGraph runtime storage is unavailable."},
        )

    @app.exception_handler(Exception)
    async def execution_error(_request: Request, error: Exception) -> JSONResponse:
        if _is_storage_error(error):
            return JSONResponse(
                status_code=503,
                content={"detail": "The LangGraph runtime storage is unavailable."},
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "The graph execution failed."},
        )


def _is_storage_error(error: Exception) -> bool:
    module = error.__class__.__module__.split(".", maxsplit=1)[0]
    return module in {"psycopg", "psycopg_pool", "redis"}
