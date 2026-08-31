from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from arclith.adapters.inbound.langgraph_runtime.catalog import ThreadAlreadyExistsError
from arclith.adapters.inbound.langgraph_runtime.coordination import RunBusyError
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
    _RuntimeEndpoints(runtime).register(app)
    _register_exception_handlers(app)
    return app


class _RuntimeEndpoints:
    def __init__(self, runtime: LangGraphRuntime) -> None:
        self.runtime = runtime

    def register(self, app: FastAPI) -> None:
        app.add_api_route(
            "/info",
            self.info,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses={503: {"description": "Runtime unavailable"}},
        )
        app.add_api_route(
            "/health",
            self.health,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses={503: {"description": "Runtime unavailable"}},
        )
        app.add_api_route(
            "/ready",
            self.ready,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses={503: {"description": "Runtime storage unavailable"}},
        )
        app.add_api_route(
            "/assistants/search",
            self.search_assistants,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses={503: {"description": "Runtime unavailable"}},
        )
        app.add_api_route(
            "/assistants/{assistant_id}",
            self.get_assistant,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/search",
            self.search_threads,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses={503: {"description": "Runtime storage unavailable"}},
        )
        app.add_api_route(
            "/threads",
            self.create_thread,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses={
                409: {"description": "Thread already exists"},
                503: {"description": "Runtime storage unavailable"},
            },
        )
        app.add_api_route(
            "/threads/{thread_id}",
            self.get_thread,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}",
            self.delete_thread,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}/state",
            self.get_thread_state,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}/history",
            self.get_thread_history,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}/runs/wait",
            self.wait_for_run,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses=_RUN_ERRORS,
        )
        app.add_api_route(
            "/threads/{thread_id}/runs/stream",
            self.stream_run,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            responses=_RUN_ERRORS,
        )
        app.add_api_route(
            "/threads/{thread_id}/runs",
            self.list_runs,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}/runs/{run_id}",
            self.get_run,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            responses=_NOT_FOUND,
        )
        app.add_api_route(
            "/threads/{thread_id}/runs/{run_id}/cancel",
            self.cancel_run,
            methods=["POST"],
            status_code=status.HTTP_204_NO_CONTENT,
            responses=_NOT_FOUND,
        )

    async def info(self) -> dict[str, Any]:
        return {
            "version": "arclith-open-source",
            "flags": {"assistants": True, "crons": False, "langsmith": False},
            "host": {"kind": "self-hosted-open-source"},
        }

    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def ready(self) -> dict[str, str]:
        if not await self.runtime.ready():
            raise RuntimeStorageError("Runtime storage is not ready")
        return {"status": "ready"}

    async def search_assistants(self) -> list[dict[str, Any]]:
        return self.runtime.assistants()

    async def get_assistant(self, assistant_id: str) -> dict[str, Any]:
        return self.runtime.assistant(assistant_id)

    async def search_threads(
        self, payload: ThreadSearchPayload
    ) -> list[dict[str, Any]]:
        records = await self.runtime.search_threads(
            metadata=payload.metadata,
            status=payload.status,
            limit=payload.limit,
            offset=payload.offset,
        )
        return [record.as_api_dict() for record in records]

    async def create_thread(self, payload: ThreadCreatePayload) -> dict[str, Any]:
        record = await self.runtime.create_thread(
            thread_id=str(payload.thread_id) if payload.thread_id else None,
            metadata=payload.metadata,
            if_exists=payload.if_exists,
        )
        return record.as_api_dict()

    async def get_thread(self, thread_id: UUID) -> dict[str, Any]:
        return (await self.runtime.get_thread(str(thread_id))).as_api_dict()

    async def delete_thread(self, thread_id: UUID) -> Response:
        await self.runtime.delete_thread(str(thread_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def get_thread_state(self, thread_id: UUID) -> dict[str, Any]:
        return await self.runtime.state(str(thread_id))

    async def get_thread_history(
        self,
        thread_id: UUID,
        payload: ThreadHistoryPayload,
    ) -> list[dict[str, Any]]:
        return await self.runtime.history(str(thread_id), limit=payload.limit)

    async def wait_for_run(self, thread_id: UUID, payload: RunPayload) -> Any:
        return await self.runtime.wait(
            str(thread_id),
            payload.as_runtime_request(),
        )

    async def stream_run(
        self, thread_id: UUID, payload: RunPayload
    ) -> StreamingResponse:
        resolved_thread = str(thread_id)
        await self.runtime.get_thread(resolved_thread)
        self.runtime.assistant(payload.assistant_id)
        return StreamingResponse(
            self.runtime.stream(resolved_thread, payload.as_runtime_request()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def list_runs(
        self,
        thread_id: UUID,
        limit: int = Query(default=10, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        run_status: str | None = Query(default=None, alias="status"),
    ) -> list[dict[str, Any]]:
        runs = await self.runtime.list_runs(
            str(thread_id),
            status=run_status,
            limit=limit,
            offset=offset,
        )
        return [run.as_api_dict() for run in runs]

    async def get_run(self, thread_id: UUID, run_id: UUID) -> dict[str, Any]:
        return (await self.runtime.get_run(str(thread_id), str(run_id))).as_api_dict()

    async def cancel_run(self, thread_id: UUID, run_id: UUID) -> Response:
        await self.runtime.cancel_run(str(thread_id), str(run_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)


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
