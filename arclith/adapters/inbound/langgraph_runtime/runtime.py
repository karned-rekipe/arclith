from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from uuid6 import uuid7

from arclith.adapters.inbound.langgraph_runtime.catalog import (
    RunRecord,
    RuntimeCatalog,
    ThreadRecord,
)
from arclith.adapters.inbound.langgraph_runtime.coordination import (
    RunBusyError,
    RunCoordinator,
)
from arclith.adapters.inbound.langgraph_runtime.serialization import (
    jsonable,
    safe_error,
    snapshot_to_dict,
    sse_event,
)
from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.domain.ports.outbound.observability import (
    ObservabilityRuntimePort,
    TraceSpan,
)


class ThreadNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class AssistantNotFoundError(LookupError):
    pass


class RunCancelledError(RuntimeError):
    pass


class RuntimeStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunRequest:
    assistant_id: str
    input: Any = None
    command: Any = None
    config: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_id: str | None = None
    stream_mode: str | list[str] | None = None
    on_disconnect: str = "cancel"
    multitask_strategy: str = "reject"
    trace_context: Mapping[str, str] | None = None


class LangGraphRuntime:
    def __init__(
        self,
        graphs: Mapping[str, Any],
        catalog: RuntimeCatalog,
        coordinator: RunCoordinator,
        *,
        run_timeout_seconds: int = 900,
        cancel_poll_seconds: float = 0.2,
        observability_runtime: ObservabilityRuntimePort | None = None,
    ) -> None:
        if not graphs:
            raise ValueError("Le runtime LangGraph exige au moins un graphe")
        if run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds doit etre strictement positif")
        if cancel_poll_seconds <= 0:
            raise ValueError("cancel_poll_seconds doit etre strictement positif")
        self.graphs = dict(graphs)
        self.catalog = catalog
        self.coordinator = coordinator
        self.run_timeout_seconds = run_timeout_seconds
        self.cancel_poll_seconds = cancel_poll_seconds
        self.observability_runtime = (
            observability_runtime
            if observability_runtime is not None
            else NoOpObservabilityRuntime()
        )

    def extract_trace_context(self, carrier: Mapping[str, str]) -> dict[str, str]:
        return dict(self.observability_runtime.propagator.extract(carrier))

    async def setup(self) -> None:
        await self.catalog.setup()

    async def ready(self) -> bool:
        catalog_ready, coordinator_ready = await asyncio.gather(
            self.catalog.healthcheck(),
            self.coordinator.healthcheck(),
        )
        return catalog_ready and coordinator_ready

    def assistant(self, assistant_id: str) -> dict[str, Any]:
        self._graph(assistant_id)
        return {
            "assistant_id": assistant_id,
            "graph_id": assistant_id,
            "name": assistant_id,
            "metadata": {"runtime": "arclith-open-source"},
            "config": {},
            "version": 1,
        }

    def assistants(self) -> list[dict[str, Any]]:
        return [self.assistant(assistant_id) for assistant_id in self.graphs]

    async def create_thread(
        self,
        *,
        thread_id: str | None,
        metadata: dict[str, Any] | None,
        if_exists: str | None,
    ) -> ThreadRecord:
        resolved_id = thread_id or str(uuid7())
        return await self.catalog.create_thread(
            resolved_id,
            metadata or {},
            if_exists=if_exists,
        )

    async def get_thread(self, thread_id: str) -> ThreadRecord:
        record = await self.catalog.get_thread(thread_id)
        if record is None:
            raise ThreadNotFoundError(f"Thread {thread_id} not found")
        return record

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ThreadRecord]:
        return await self.catalog.search_threads(
            metadata=metadata,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def delete_thread(self, thread_id: str) -> None:
        await self.get_thread(thread_id)
        async with self.coordinator.thread_lock(
            thread_id,
            timeout_seconds=self.run_timeout_seconds,
        ):
            seen: set[int] = set()
            for graph in self.graphs.values():
                checkpointer = getattr(graph, "checkpointer", None)
                if checkpointer is None or id(checkpointer) in seen:
                    continue
                seen.add(id(checkpointer))
                delete = getattr(checkpointer, "adelete_thread", None)
                if callable(delete):
                    await delete(thread_id)
            await self.catalog.delete_thread(thread_id)

    async def state(self, thread_id: str) -> dict[str, Any]:
        await self.get_thread(thread_id)
        graph = await self._thread_graph(thread_id)
        snapshot = await graph.aget_state(_graph_config(thread_id, None))
        if not snapshot.config:
            return _empty_snapshot(thread_id)
        return snapshot_to_dict(snapshot)

    async def history(self, thread_id: str, *, limit: int) -> list[dict[str, Any]]:
        await self.get_thread(thread_id)
        graph = await self._thread_graph(thread_id)
        snapshots = graph.aget_state_history(
            _graph_config(thread_id, None),
            limit=limit,
        )
        return [snapshot_to_dict(snapshot) async for snapshot in snapshots]

    async def wait(self, thread_id: str, request: RunRequest) -> Any:
        await self.get_thread(thread_id)
        graph = self._graph(request.assistant_id)
        async with self._run_session(thread_id, request) as run:
            with self._trace_execution(thread_id, run.run_id, request) as span:
                async with asyncio.timeout(self.run_timeout_seconds):
                    output = await self._invoke(
                        graph,
                        thread_id,
                        run.run_id,
                        request,
                    )
                encoded = jsonable(output)
                await self.catalog.finish_run(
                    run.run_id,
                    status="success",
                    output=encoded,
                )
                span.set_metadata({"langgraph.run.status": "success"})
                return encoded

    async def stream(
        self,
        thread_id: str,
        request: RunRequest,
    ) -> AsyncIterator[bytes]:
        await self.get_thread(thread_id)
        graph = self._graph(request.assistant_id)
        stream = None
        try:
            async with self._run_session(thread_id, request) as run:
                with self._trace_execution(thread_id, run.run_id, request) as span:
                    async with asyncio.timeout(self.run_timeout_seconds):
                        modes = _stream_modes(request.stream_mode)
                        stream = graph.astream(
                            _run_input(request),
                            _graph_config(thread_id, request),
                            stream_mode=modes,
                        )
                        yield sse_event(
                            "metadata",
                            {"run_id": run.run_id, "thread_id": thread_id},
                        )
                        async for mode, chunk in self._cancel_aware_stream(
                            stream,
                            run.run_id,
                            modes,
                        ):
                            yield sse_event(mode, chunk)
                    state = await graph.aget_state(_graph_config(thread_id, None))
                    output = jsonable(state.values) if state.config else None
                    await self.catalog.finish_run(
                        run.run_id,
                        status="success",
                        output=output,
                    )
                    span.set_metadata({"langgraph.run.status": "success"})
        except asyncio.CancelledError:
            raise
        except RunBusyError:
            yield sse_event(
                "error",
                {
                    "error": "RunBusyError",
                    "message": "Thread already has an active run.",
                },
            )
        except RunCancelledError:
            yield sse_event(
                "error",
                {"error": "RunCancelledError", "message": "Run cancelled."},
            )
        except Exception:
            yield _execution_error_event()
        finally:
            await _close_stream(stream)

    async def cancel_run(self, thread_id: str, run_id: str) -> None:
        run = await self.get_run(thread_id, run_id)
        if run.status != "running":
            return
        await self.coordinator.request_cancel(run_id)

    async def get_run(self, thread_id: str, run_id: str) -> RunRecord:
        record = await self.catalog.get_run(thread_id, run_id)
        if record is None:
            raise RunNotFoundError(f"Run {run_id} not found")
        return record

    async def list_runs(
        self,
        thread_id: str,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[RunRecord]:
        await self.get_thread(thread_id)
        return await self.catalog.list_runs(
            thread_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def _start_run(self, thread_id: str, request: RunRequest) -> RunRecord:
        record = RunRecord(
            run_id=str(uuid7()),
            thread_id=thread_id,
            assistant_id=request.assistant_id,
            status="running",
            input=jsonable(request.input),
        )
        return await self.catalog.create_run(record)

    async def _thread_graph(self, thread_id: str) -> Any:
        runs = await self.catalog.list_runs(
            thread_id,
            status=None,
            limit=1,
            offset=0,
        )
        if runs:
            return self._graph(runs[0].assistant_id)
        return next(iter(self.graphs.values()))

    @asynccontextmanager
    async def _run_session(
        self,
        thread_id: str,
        request: RunRequest,
    ) -> AsyncIterator[RunRecord]:
        async with self.coordinator.thread_lock(
            thread_id,
            timeout_seconds=self.run_timeout_seconds,
        ):
            run = await self._start_run(thread_id, request)
            try:
                yield run
            except asyncio.CancelledError as error:
                if request.on_disconnect == "cancel":
                    await self.coordinator.request_cancel(run.run_id)
                await self._finish_error(run.run_id, "interrupted", error)
                raise
            except RunCancelledError as error:
                await self._finish_error(run.run_id, "interrupted", error)
                raise
            except Exception as error:
                await self._finish_error(run.run_id, "error", error)
                raise
            finally:
                with suppress(Exception):
                    await self.coordinator.clear_cancel(run.run_id)

    async def _finish_error(
        self, run_id: str, status: str, error: BaseException
    ) -> None:
        await self.catalog.finish_run(
            run_id,
            status=status,
            error=safe_error(error),
        )

    async def _invoke(
        self,
        graph: Any,
        thread_id: str,
        run_id: str,
        request: RunRequest,
    ) -> Any:
        execution = asyncio.create_task(
            graph.ainvoke(
                _run_input(request),
                _graph_config(thread_id, request),
            )
        )
        cancellation = asyncio.create_task(self._wait_for_cancel(run_id))
        try:
            done, _pending = await asyncio.wait(
                {execution, cancellation},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done:
                try:
                    await cancellation
                except Exception:
                    execution.cancel()
                    with suppress(asyncio.CancelledError):
                        await execution
                    raise
                execution.cancel()
                with suppress(asyncio.CancelledError):
                    await execution
                raise RunCancelledError(f"Run {run_id} cancelled")
            return await execution
        finally:
            cancellation.cancel()
            with suppress(asyncio.CancelledError):
                await cancellation

    async def _cancel_aware_stream(
        self,
        stream: Any,
        run_id: str,
        modes: list[str],
    ) -> AsyncIterator[tuple[str, Any]]:
        iterator = stream.__aiter__()
        while True:
            next_item = asyncio.create_task(anext(iterator))
            cancellation = asyncio.create_task(self._wait_for_cancel(run_id))
            try:
                done, _pending = await asyncio.wait(
                    {next_item, cancellation},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation in done:
                    try:
                        await cancellation
                    except Exception:
                        next_item.cancel()
                        with suppress(asyncio.CancelledError, StopAsyncIteration):
                            await next_item
                        raise
                    next_item.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await next_item
                    raise RunCancelledError(f"Run {run_id} cancelled")
                try:
                    item = await next_item
                except StopAsyncIteration:
                    return
                yield _stream_item(item, modes)
            finally:
                cancellation.cancel()
                with suppress(asyncio.CancelledError):
                    await cancellation

    async def _wait_for_cancel(self, run_id: str) -> None:
        while not await self.coordinator.is_cancelled(run_id):
            await asyncio.sleep(self.cancel_poll_seconds)

    @contextmanager
    def _trace_execution(
        self,
        thread_id: str,
        run_id: str,
        request: RunRequest,
    ) -> Iterator[TraceSpan]:
        metadata = {
            "langgraph.thread_id": thread_id,
            "langgraph.run_id": run_id,
            "langgraph.assistant_id": request.assistant_id,
        }
        parent = self.extract_trace_context(request.trace_context or {})
        with (
            self.observability_runtime.propagator.context(parent),
            self.observability_runtime.tracer.span(
                "langgraph.runtime.run",
                kind="server",
                tags=("langgraph-runtime",),
                metadata=metadata,
            ) as span,
        ):
            try:
                yield span
            except (asyncio.CancelledError, RunCancelledError):
                span.set_metadata({"langgraph.run.status": "interrupted"})
                raise
            except BaseException:
                span.set_metadata({"langgraph.run.status": "error"})
                raise

    def _graph(self, assistant_id: str) -> Any:
        graph = self.graphs.get(assistant_id)
        if graph is None:
            raise AssistantNotFoundError(f"Assistant {assistant_id} not found")
        return graph


def _run_input(request: RunRequest) -> Any:
    if request.command is None:
        return request.input
    if not isinstance(request.command, Mapping):
        return request.command
    from langgraph.types import Command

    return Command(**request.command)


def _graph_config(thread_id: str, request: RunRequest | None) -> dict[str, Any]:
    configured = dict(request.config or {}) if request is not None else {}
    configurable = dict(configured.get("configurable") or {})
    configurable["thread_id"] = thread_id
    if request is not None:
        checkpoint = request.checkpoint or {}
        checkpoint_id = request.checkpoint_id or checkpoint.get("checkpoint_id")
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id
        if checkpoint.get("checkpoint_ns") is not None:
            configurable["checkpoint_ns"] = checkpoint["checkpoint_ns"]
    configured["configurable"] = configurable
    return configured


def _stream_modes(configured: str | list[str] | None) -> list[str]:
    modes = [configured] if isinstance(configured, str) else list(configured or [])
    if not modes:
        modes = ["values"]
    normalized = ["messages" if mode == "messages-tuple" else mode for mode in modes]
    return list(dict.fromkeys(normalized))


def _stream_item(item: Any, modes: list[str]) -> tuple[str, Any]:
    if len(modes) > 1 and isinstance(item, tuple) and len(item) == 2:
        return str(item[0]), item[1]
    return modes[0], item


def _empty_snapshot(thread_id: str) -> dict[str, Any]:
    return {
        "values": {},
        "next": [],
        "tasks": [],
        "metadata": None,
        "created_at": None,
        "checkpoint": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": None,
        },
        "parent_checkpoint": None,
    }


def _execution_error_event() -> bytes:
    return sse_event(
        "error",
        {
            "error": "GraphExecutionError",
            "message": "The graph execution failed.",
        },
    )


async def _close_stream(stream: Any) -> None:
    if stream is None:
        return
    close = getattr(stream, "aclose", None)
    if callable(close):
        with suppress(RuntimeError):
            await close()
