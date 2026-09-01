from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from typing import Any

from arclith.adapters.outbound.langsmith.config import ResolvedLangSmithConfig
from arclith.adapters.outbound.langsmith.propagation import (
    filter_baggage,
    merge_baggage,
)
from arclith.infrastructure.config import LangSmithSettings


class LangSmithIntegrationMixin:
    """Propagate trace context and bridge LangSmith with OpenTelemetry."""

    settings: LangSmithSettings
    _opentelemetry_enabled: bool
    _otel_provider: Any | None
    _otel_processor: Any | None
    _owns_otel_provider: bool

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _require_resolved(self) -> ResolvedLangSmithConfig:
        raise NotImplementedError

    @abstractmethod
    def _handle_runtime_error(self, operation: str, exc: Exception) -> None:
        raise NotImplementedError

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
            for key in ("traceparent", "tracestate"):
                if value := carrier.get(key):
                    headers.setdefault(key, value)
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
