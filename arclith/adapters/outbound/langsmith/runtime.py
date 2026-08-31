from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Any

from arclith.adapters.outbound.langsmith.config import (
    ResolvedLangSmithConfig,
    resolve_langsmith_config,
)
from arclith.adapters.outbound.langsmith.integration import LangSmithIntegrationMixin
from arclith.adapters.outbound.langsmith.privacy import trace_metadata, trace_payload
from arclith.adapters.outbound.langsmith.propagation import normalized_parent_headers
from arclith.adapters.outbound.noop.observability import NoOpTraceSpan
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.observability import (
    TraceAnonymizer,
    TracePort,
    TraceSpan,
)
from arclith.infrastructure.config import LangSmithSettings

_RUN_TYPES = frozenset(
    {"chain", "llm", "tool", "retriever", "embedding", "prompt", "parser"}
)


class LangSmithTraceSpan(TraceSpan):
    def __init__(self, run_tree: Any, resolved: ResolvedLangSmithConfig) -> None:
        self._run_tree = run_tree
        self._resolved = resolved

    def set_outputs(self, outputs: object | None) -> None:
        self._run_tree.end(
            outputs=trace_payload(outputs, enabled=self._resolved.capture_outputs)
        )

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        if not self._resolved.capture_metadata:
            return
        self._run_tree.metadata.update(trace_metadata(metadata, enabled=True))


class LangSmithRuntime(LangSmithIntegrationMixin, TracePort):
    """Lazy LangSmith runtime. LangSmith imports remain confined to this adapter."""

    def __init__(
        self,
        settings: LangSmithSettings,
        logger: Logger,
        *,
        service_metadata: Mapping[str, object] | None = None,
        opentelemetry_enabled: bool = False,
        anonymizer: TraceAnonymizer | None = None,
        before_start: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self._logger = logger
        self._service_metadata = dict(service_metadata or {})
        self._opentelemetry_enabled = opentelemetry_enabled
        self._anonymizer = anonymizer
        self._before_start = before_start
        self._lock = threading.RLock()
        self._started = False
        self._closed = False
        self._client: Any | None = None
        self._langsmith: Any | None = None
        self._resolved: ResolvedLangSmithConfig | None = None
        self._otel_provider: Any | None = None
        self._otel_processor: Any | None = None
        self._owns_otel_provider = False
        self._reported_errors: set[str] = set()
        self._enabled_override: ContextVar[bool | None] = ContextVar(
            "arclith_langsmith_enabled",
            default=None,
        )

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            if self._closed:
                raise RuntimeError("Le runtime LangSmith est deja ferme")
            resolved = resolve_langsmith_config(self.settings)
            try:
                import langsmith
            except ImportError as exc:
                raise RuntimeError(
                    "observability.enabled contient langsmith; installez l'extra "
                    '"arclith[langsmith]".'
                ) from exc

            if self._before_start is not None:
                self._before_start()

            self._langsmith = langsmith
            self._resolved = resolved
            self._client = langsmith.Client(
                api_url=resolved.endpoint,
                api_key=resolved.api_key,
                workspace_id=resolved.workspace_id,
                anonymizer=self._anonymizer,
                hide_inputs=not resolved.capture_inputs,
                hide_outputs=not resolved.capture_outputs,
                hide_metadata=not resolved.capture_metadata,
                tracing_mode=resolved.tracing_mode,
                tracing_sampling_rate=resolved.sampling_rate,
                tracing_error_callback=self._on_export_error,
            )
            langsmith.configure(
                client=self._client,
                enabled=(
                    resolved.tracing_enabled
                    and resolved.sampling_rate > 0
                    and self.settings.instrumentation.langgraph
                ),
                project_name=resolved.project,
                tags=list(self.settings.tags),
                metadata=self._default_metadata(),
            )
            self._started = True
            if self._opentelemetry_enabled and resolved.tracing_mode == "otel":
                self._attach_to_current_otel_provider()
            self._diagnostic(
                "LangSmith runtime initialise",
                project=resolved.project,
                endpoint=resolved.endpoint,
                tracing=resolved.tracing_enabled,
                tracing_mode=resolved.tracing_mode,
                sampling_rate=resolved.sampling_rate,
            )

    def client(self) -> Any:
        self.start()
        return self._client

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        self.start()
        resolved = self._require_resolved()
        override = self._enabled_override.get()
        if override is False or (override is None and not resolved.tracing_enabled):
            yield NoOpTraceSpan()
            return

        opened = self._open_span(name, kind, inputs, tags, metadata)
        if opened is None:
            yield NoOpTraceSpan()
            return

        trace_context, run_tree = opened
        span = LangSmithTraceSpan(run_tree, resolved)
        try:
            yield span
        except BaseException as exc:
            self._finish_span(trace_context, exc)
            raise
        else:
            self._finish_span(trace_context)

    def _open_span(
        self,
        name: str,
        kind: str,
        inputs: object | None,
        tags: Sequence[str],
        metadata: Mapping[str, object] | None,
    ) -> tuple[Any, Any] | None:
        resolved = self._require_resolved()
        combined_metadata = {**self._default_metadata(), **dict(metadata or {})}
        stack = ExitStack()
        try:
            stack.enter_context(
                self._require_langsmith().tracing_context(
                    enabled=True,
                    client=self._client,
                )
            )
            run_tree = stack.enter_context(
                self._require_langsmith().trace(
                    name,
                    run_type=kind if kind in _RUN_TYPES else "chain",
                    inputs=trace_payload(inputs, enabled=resolved.capture_inputs),
                    project_name=None,
                    tags=[*self.settings.tags, *tags],
                    metadata=trace_metadata(
                        combined_metadata,
                        enabled=resolved.capture_metadata,
                    ),
                    client=self._client,
                )
            )
            return stack, run_tree
        except Exception as exc:
            self._close_failed_stack(stack, "span.start.cleanup")
            self._handle_runtime_error("span.start", exc)
            return None

    def _close_failed_stack(self, stack: ExitStack, operation: str) -> None:
        try:
            stack.close()
        except Exception as exc:
            self._handle_runtime_error(operation, exc)

    def _finish_span(
        self, trace_context: Any, error: BaseException | None = None
    ) -> None:
        exc_info = (
            (type(error), error, error.__traceback__)
            if error is not None
            else (None, None, None)
        )
        operation = "span.error.close" if error is not None else "span.close"
        try:
            trace_context.__exit__(*exc_info)
        except Exception as exc:
            self._handle_runtime_error(operation, exc)

    @contextmanager
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        self.start()
        resolved = self._require_resolved()
        safe_parent = normalized_parent_headers(
            parent,
            allowlist=set(self.settings.propagation.baggage_allowlist),
            langsmith_headers=self.settings.propagation.langsmith_headers,
            traceparent=self.settings.propagation.traceparent,
        )
        token = self._enabled_override.set(enabled)
        stack = ExitStack()
        try:
            try:
                stack.enter_context(self._otel_parent_context(safe_parent))
                stack.enter_context(
                    self._require_langsmith().tracing_context(
                        enabled=enabled,
                        project_name=project or resolved.project,
                        tags=[*self.settings.tags, *tags],
                        metadata=trace_metadata(
                            {**self._default_metadata(), **dict(metadata or {})},
                            enabled=resolved.capture_metadata,
                        ),
                        parent=safe_parent or None,
                        client=self._client,
                    )
                )
            except Exception as exc:
                self._close_failed_stack(stack, "context.start.cleanup")
                self._handle_runtime_error("context.start", exc)
                yield
                return
            try:
                yield
            except BaseException:
                try:
                    stack.close()
                except Exception as exc:
                    self._handle_runtime_error("context.error.close", exc)
                raise
            else:
                try:
                    stack.close()
                except Exception as exc:
                    self._handle_runtime_error("context.close", exc)
        finally:
            self._enabled_override.reset(token)

    def flush(self, timeout: float | None = None) -> None:
        if not self._started or self._closed:
            return
        resolved_timeout = timeout or self.settings.lifecycle.flush_timeout_seconds
        self._flush_otel(resolved_timeout)
        self._flush_client(resolved_timeout)

    def _flush_otel(self, timeout: float) -> None:
        if self._otel_processor is None:
            return
        try:
            self._otel_processor.force_flush(timeout_millis=max(1, int(timeout * 1000)))
        except Exception as exc:
            self._handle_runtime_error("otel.flush", exc)

    def _flush_client(self, timeout: float) -> None:
        if self._client is None:
            return
        try:
            self._client.flush(timeout=timeout)
        except Exception as exc:
            self._handle_runtime_error("client.flush", exc)

    def close(self, timeout: float | None = None) -> None:
        with self._lock:
            if not self._started or self._closed:
                return
            resolved_timeout = timeout or self.settings.lifecycle.flush_timeout_seconds
            self.flush(resolved_timeout)
            self._close_otel()
            self._close_client(resolved_timeout)
            self._reset_langsmith_configuration()
            self._closed = True

    def _close_otel(self) -> None:
        try:
            if self._owns_otel_provider and self._otel_provider is not None:
                self._otel_provider.shutdown()
            elif self._otel_processor is not None:
                self._otel_processor.shutdown()
        except Exception as exc:
            self._handle_runtime_error("otel.close", exc)

    def _close_client(self, timeout: float) -> None:
        if self._client is None:
            return
        try:
            self._client.close(timeout=timeout)
        except Exception as exc:
            self._handle_runtime_error("client.close", exc)

    def _reset_langsmith_configuration(self) -> None:
        if self._langsmith is None:
            return
        try:
            self._langsmith.configure(
                client=None,
                enabled=None,
                project_name=None,
                tags=None,
                metadata=None,
            )
        except Exception as exc:
            self._handle_runtime_error("configuration.reset", exc)

    def diagnostics(self) -> Mapping[str, object]:
        resolved = self._resolved
        return {
            "backend": "langsmith",
            "started": self._started,
            "closed": self._closed,
            "tracing": resolved.tracing_enabled
            if resolved
            else self.settings.tracing.enabled,
            "mode": resolved.tracing_mode if resolved else self.settings.tracing.mode,
            "project": resolved.project if resolved else self.settings.project,
            "sampling_rate": (
                resolved.sampling_rate
                if resolved
                else self.settings.tracing.sampling_rate
            ),
            "capture": {
                "inputs": resolved.capture_inputs
                if resolved
                else self.settings.capture.inputs,
                "outputs": resolved.capture_outputs
                if resolved
                else self.settings.capture.outputs,
                "metadata": (
                    resolved.capture_metadata
                    if resolved
                    else self.settings.capture.metadata
                ),
                "model_content": self.settings.capture.model_content,
                "binary_content": self.settings.capture.binary_content,
            },
        }

    def _default_metadata(self) -> dict[str, object]:
        return {**self._service_metadata, **self.settings.metadata}

    def _require_resolved(self) -> ResolvedLangSmithConfig:
        if self._resolved is None:
            raise RuntimeError("Le runtime LangSmith n'est pas initialise")
        return self._resolved

    def _require_langsmith(self) -> Any:
        if self._langsmith is None:
            raise RuntimeError("Le runtime LangSmith n'est pas initialise")
        return self._langsmith

    def _on_export_error(self, exc: Exception) -> None:
        self._handle_runtime_error("export", exc)

    def _handle_runtime_error(self, operation: str, exc: Exception) -> None:
        key = f"{operation}:{type(exc).__name__}"
        if key not in self._reported_errors:
            self._reported_errors.add(key)
            self._logger.warning(
                "LangSmith telemetry failure (fail-open)",
                operation=operation,
                error_type=type(exc).__name__,
            )
        if self.settings.failure_mode == "raise":
            raise exc

    def _diagnostic(self, message: str, **metadata: object) -> None:
        if not self.settings.diagnostics.enabled:
            return
        log = getattr(self._logger, self.settings.diagnostics.log_level)
        log(message, **metadata)
