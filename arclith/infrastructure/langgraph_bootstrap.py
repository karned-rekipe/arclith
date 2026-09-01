from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from arclith.infrastructure.config import (
    AppConfig,
    LangGraphPersistenceSettings,
    LangGraphStreamMode,
)

if TYPE_CHECKING:
    from arclith.arclith import Arclith
    from arclith.infrastructure.langgraph_persistence_factory import (
        LangGraphPersistenceComponents,
        LangGraphPersistenceRegistry,
    )

LANGGRAPH_UNSET = object()
LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR = "_arclith_observability_runtime"


def _normalize_langgraph_stream_mode(
    stream_mode: LangGraphStreamMode | Sequence[LangGraphStreamMode],
) -> LangGraphStreamMode | list[LangGraphStreamMode]:
    if isinstance(stream_mode, str):
        return stream_mode
    return list(stream_mode)


def _langgraph_persistence_settings(
    config: AppConfig,
) -> LangGraphPersistenceSettings | None:
    if config.langgraph is None:
        return None
    return config.langgraph.persistence


def _langgraph_persistence_requested(
    settings: LangGraphPersistenceSettings | None,
    override: bool | None,
) -> bool:
    if override is not None:
        return override
    return settings is not None and settings.enabled


def _require_langgraph_persistence(
    settings: LangGraphPersistenceSettings | None,
) -> LangGraphPersistenceSettings:
    if settings is None or not settings.enabled:
        raise RuntimeError(
            "persistence=True requiert langgraph.persistence.enabled=true dans la configuration Arclith"
        )
    return settings


def _langgraph_compile_value(value: Any) -> Any:
    return None if value is LANGGRAPH_UNSET else value


def _langgraph_configured_value(explicit: Any, configured: object | None) -> Any:
    return configured if explicit is LANGGRAPH_UNSET else explicit


class LangGraphBootstrap:
    """Compile LangGraph agents and own their optional persistence resources."""

    def __init__(self, owner: "Arclith") -> None:
        self._owner = owner

    def langgraph(
        self,
        state_schema: type[Any],
        register_graph: Callable[[Any, "Arclith"], None],
        *,
        context_schema: type[Any] | None = None,
        input_schema: type[Any] | None = None,
        output_schema: type[Any] | None = None,
        name: str = "agent",
        checkpointer: Any = LANGGRAPH_UNSET,
        cache: Any = None,
        store: Any = LANGGRAPH_UNSET,
        interrupt_before: Any = None,
        interrupt_after: Any = None,
        debug: bool = False,
        stream_mode: LangGraphStreamMode | Sequence[LangGraphStreamMode] | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        persistence: bool | None = None,
        persistence_registry: LangGraphPersistenceRegistry | None = None,
    ) -> Any:
        if self._owner._langsmith_instrumentation_enabled(
            "langgraph"
        ) or self._owner._opentelemetry_instrumentation_enabled("langgraph", "traces"):
            self._owner._start_observability()
        from langgraph.graph import StateGraph

        builder = StateGraph(
            state_schema,
            context_schema=context_schema,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        register_graph(builder, self._owner)
        (
            resolved_checkpointer,
            resolved_store,
            persistence_components,
        ) = self._resolve_langgraph_persistence(
            checkpointer=checkpointer,
            store=store,
            persistence=persistence,
            registry=persistence_registry,
        )
        try:
            compiled = builder.compile(
                checkpointer=resolved_checkpointer,
                cache=cache,
                store=resolved_store,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                debug=debug,
                name=name,
                transformers=transformers,
            )
        except BaseException:
            if persistence_components is not None:
                persistence_components.close()
            raise
        compiled = self._owner._observability_runtime.instrument_langgraph(
            compiled, name=name
        )
        setattr(
            compiled,
            LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR,
            self._owner._observability_runtime,
        )
        if persistence_components is not None:
            self._remember_langgraph_persistence(persistence_components)
            setattr(compiled, "_arclith_persistence", persistence_components)
        resolved_stream_mode = stream_mode
        if resolved_stream_mode is None and self._owner.config.langgraph is not None:
            resolved_stream_mode = self._owner.config.langgraph.stream_mode
        if resolved_stream_mode is not None:
            setattr(
                compiled,
                "stream_mode",
                _normalize_langgraph_stream_mode(resolved_stream_mode),
            )
        return compiled

    def _resolve_langgraph_persistence(
        self,
        *,
        checkpointer: Any,
        store: Any,
        persistence: bool | None,
        registry: LangGraphPersistenceRegistry | None,
    ) -> tuple[Any, Any, "LangGraphPersistenceComponents | None"]:
        checkpointer_is_explicit = checkpointer is not LANGGRAPH_UNSET
        store_is_explicit = store is not LANGGRAPH_UNSET
        persistence_settings = _langgraph_persistence_settings(self._owner.config)
        if not _langgraph_persistence_requested(persistence_settings, persistence):
            return (
                _langgraph_compile_value(checkpointer),
                _langgraph_compile_value(store),
                None,
            )
        if checkpointer_is_explicit and store_is_explicit:
            return checkpointer, store, None

        persistence_settings = _require_langgraph_persistence(persistence_settings)
        from arclith.infrastructure.langgraph_persistence_factory import (
            build_langgraph_persistence,
        )

        components = build_langgraph_persistence(
            persistence_settings,
            registry=registry,
            include_checkpointer=not checkpointer_is_explicit,
            include_store=not store_is_explicit,
        )
        resolved_checkpointer = _langgraph_configured_value(
            checkpointer, components.checkpointer
        )
        resolved_store = _langgraph_configured_value(store, components.store)
        if components.mode == "agent_server":
            components.close()
            return resolved_checkpointer, resolved_store, None
        return resolved_checkpointer, resolved_store, components

    def langgraph_memory_namespace(self, **values: object) -> tuple[str, ...]:
        settings = (
            self._owner.config.langgraph.persistence
            if self._owner.config.langgraph is not None
            else None
        )
        if settings is None:
            raise RuntimeError("langgraph.persistence n'est pas configure")
        from arclith.infrastructure.langgraph_persistence_factory import (
            render_langgraph_namespace,
        )

        return render_langgraph_namespace(settings.store.namespace_template, values)

    def close_langgraph_persistence(self) -> None:
        resources: list[LangGraphPersistenceComponents] = self.__dict__.pop(
            "_langgraph_persistence_resources", []
        )
        for resource in reversed(resources):
            resource.close()

    def _remember_langgraph_persistence(
        self, components: "LangGraphPersistenceComponents"
    ) -> None:
        resources = self.__dict__.setdefault("_langgraph_persistence_resources", [])
        resources.append(components)
