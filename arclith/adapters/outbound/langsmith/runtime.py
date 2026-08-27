from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Any

from arclith.adapters.outbound.langsmith.config import (
    ResolvedLangSmithConfig,
    resolve_langsmith_config,
)
from arclith.adapters.outbound.langsmith.privacy import trace_metadata, trace_payload
from arclith.adapters.outbound.langsmith.propagation import (
    filter_baggage,
    merge_baggage,
    normalized_parent_headers,
)
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


class LangSmithRuntime(TracePort):
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

    def inject(self, headers: MutableMapping[str, str]) -> None:
        if not self.settings.propagation.enabled:
            return
        self.start()
        allowlist = set(self.settings.propagation.baggage_allowlist)
        native_baggage = self._inject_langsmith_context(headers, allowlist)
        otel_baggage = self._inject_otel_context(headers, allowlist)
        baggage = merge_baggage(native_baggage, otel_baggage)
        if baggage:
            headers.setdefault("baggage", baggage)

    def _inject_langsmith_context(
        self,
        headers: MutableMapping[str, str],
        allowlist: set[str],
    ) -> str:
        if not self.settings.propagation.langsmith_headers:
            return ""
        try:
            from langsmith.run_helpers import get_current_run_tree

            run_tree = get_current_run_tree()
            if run_tree is None:
                return ""
            native_headers = run_tree.to_headers()
            trace_header = native_headers.get("langsmith-trace")
            if trace_header:
                headers.setdefault("langsmith-trace", trace_header)
            return filter_baggage(
                native_headers.get("baggage", ""),
                allowlist=allowlist,
            )
        except Exception as exc:
            self._handle_runtime_error("propagation.inject.langsmith", exc)
            return ""

    def _inject_otel_context(
        self,
        headers: MutableMapping[str, str],
        allowlist: set[str],
    ) -> str:
        if not self.settings.propagation.traceparent:
            return ""
        try:
            from opentelemetry import propagate

            carrier: dict[str, str] = {}
            propagate.inject(carrier)
            traceparent = carrier.get("traceparent")
            if traceparent:
                headers.setdefault("traceparent", traceparent)
            return filter_baggage(carrier.get("baggage", ""), allowlist=allowlist)
        except ImportError:
            return ""
        except Exception as exc:
            self._handle_runtime_error("propagation.inject.otel", exc)
            return ""

    def pydantic_ai_capability(self) -> Any | None:
        if not self.settings.instrumentation.pydantic_ai:
            return None
        self.start()
        resolved = self._require_resolved()
        if not resolved.tracing_enabled or resolved.sampling_rate == 0:
            return None
        try:
            from pydantic_ai.capabilities.instrumentation import Instrumentation
            from pydantic_ai.models.instrumented import InstrumentationSettings
        except ImportError as exc:
            raise RuntimeError(
                "L'instrumentation LangSmith de Pydantic AI requiert "
                'les extras "arclith[langgraph,langsmith]".'
            ) from exc

        provider = self._ensure_pydantic_otel_provider()
        return Instrumentation(
            InstrumentationSettings(
                tracer_provider=provider,
                include_content=self.settings.capture.model_content,
                include_binary_content=self.settings.capture.binary_content,
                include_model_request_parameters=(
                    self.settings.capture.model_request_parameters
                ),
            )
        )

    def attach_to_current_opentelemetry(self) -> None:
        """Fan out the shared provider to LangSmith without replacing it."""
        self.start()
        resolved = self._require_resolved()
        if resolved.tracing_mode != "otel" or self._otel_processor is not None:
            return
        self._attach_to_current_otel_provider()

    def _attach_to_current_otel_provider(self) -> None:
        try:
            from opentelemetry import trace
        except ImportError as exc:
            raise RuntimeError(
                'Le mode LangSmith "otel" requiert "arclith[langsmith]".'
            ) from exc
        provider = trace.get_tracer_provider()
        if not hasattr(provider, "add_span_processor"):
            raise RuntimeError(
                "Aucun TracerProvider OpenTelemetry configurable n'est disponible "
                "pour composer LangSmith et OpenTelemetry"
            )
        self._attach_langsmith_processor(provider)

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

    def _ensure_pydantic_otel_provider(self) -> Any:
        if self._otel_provider is not None:
            return self._otel_provider
        try:
            from langsmith.integrations.otel.processor import OtelSpanProcessor
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError as exc:
            raise RuntimeError(
                "L'instrumentation Pydantic AI requiert OpenTelemetry. "
                'Installez "arclith[langsmith]".'
            ) from exc

        resolved = self._require_resolved()
        provider: Any = None
        if self._opentelemetry_enabled:
            candidate = trace.get_tracer_provider()
            if hasattr(candidate, "add_span_processor"):
                provider = candidate
        elif resolved.tracing_mode in {"otel", "hybrid"}:
            candidate = trace.get_tracer_provider()
            if hasattr(candidate, "add_span_processor"):
                self._otel_provider = candidate
                return candidate
        if provider is None:
            provider = TracerProvider()
            self._owns_otel_provider = True

        self._attach_langsmith_processor(provider, processor_class=OtelSpanProcessor)
        return provider

    def _attach_langsmith_processor(
        self,
        provider: Any,
        *,
        processor_class: Any | None = None,
    ) -> None:
        if self._otel_processor is not None:
            return
        if processor_class is None:
            from langsmith.integrations.otel.processor import OtelSpanProcessor

            processor_class = OtelSpanProcessor
        resolved = self._require_resolved()
        processor = processor_class(
            api_key=resolved.api_key,
            project=resolved.project,
            url=resolved.endpoint,
        )
        provider.add_span_processor(processor)
        self._otel_provider = provider
        self._otel_processor = processor

    @contextmanager
    def _otel_parent_context(self, headers: Mapping[str, str]) -> Iterator[None]:
        if not (self.settings.propagation.traceparent and headers.get("traceparent")):
            yield
            return
        try:
            from opentelemetry import context as otel_context
            from opentelemetry import propagate
        except ImportError:
            yield
            return
        token = otel_context.attach(propagate.extract(dict(headers)))
        try:
            yield
        finally:
            otel_context.detach(token)

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
