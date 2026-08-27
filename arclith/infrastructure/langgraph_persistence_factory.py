from __future__ import annotations

import importlib
import inspect
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from arclith.infrastructure.config import (
    LangGraphCheckpointerSettings,
    LangGraphPersistenceSettings,
    LangGraphSemanticSearchSettings,
    LangGraphStoreSettings,
)

PersistenceRole = Literal["checkpointer", "store"]
CheckpointerFactory = Callable[[LangGraphCheckpointerSettings], object]
StoreFactory = Callable[[LangGraphStoreSettings], object]

_DEFAULT_CONNECTION_ENV: dict[tuple[PersistenceRole, str], str] = {
    ("checkpointer", "postgresql"): "POSTGRESQL_URL",
    ("checkpointer", "mongodb"): "MONGODB_URI",
    ("store", "postgresql"): "POSTGRESQL_URL",
    ("store", "mongodb"): "MONGODB_URI",
    ("store", "redis"): "REDIS_URL",
}
_EXTRA_BY_BACKEND: dict[tuple[PersistenceRole, str], str] = {
    ("checkpointer", "memory"): "langgraph",
    ("checkpointer", "sqlite"): "langgraph-persistence-sqlite",
    ("checkpointer", "postgresql"): "langgraph-persistence-postgresql",
    ("checkpointer", "mongodb"): "langgraph-persistence-mongodb",
    ("store", "memory"): "langgraph",
    ("store", "postgresql"): "langgraph-persistence-postgresql",
    ("store", "mongodb"): "langgraph-persistence-mongodb",
    ("store", "redis"): "langgraph-persistence-redis",
}
_AGENT_SERVER_MARKERS = (
    "LANGSERVE_GRAPHS",
    "LANGSMITH_LANGGRAPH_API_VARIANT",
    "LANGGRAPH_RUNTIME_EDITION",
)


@dataclass
class LangGraphPersistenceComponents:
    """Persistence objects and their owned connection lifecycle."""

    checkpointer: object | None = None
    store: object | None = None
    mode: Literal["embedded", "agent_server"] = "embedded"
    _stack: ExitStack = field(default_factory=ExitStack, repr=False)

    def close(self) -> None:
        self._stack.close()


class LangGraphPersistenceRegistry:
    """Registry for project-specific embedded checkpointer and store factories."""

    def __init__(self) -> None:
        self._checkpointers: dict[str, CheckpointerFactory] = {}
        self._stores: dict[str, StoreFactory] = {}

    def register_checkpointer(
        self, name: str, factory: CheckpointerFactory
    ) -> "LangGraphPersistenceRegistry":
        self._checkpointers[_normalize_adapter_name(name)] = factory
        return self

    def register_store(
        self, name: str, factory: StoreFactory
    ) -> "LangGraphPersistenceRegistry":
        self._stores[_normalize_adapter_name(name)] = factory
        return self

    def checkpointer_factory(self, name: str) -> CheckpointerFactory | None:
        return self._checkpointers.get(_normalize_adapter_name(name))

    def store_factory(self, name: str) -> StoreFactory | None:
        return self._stores.get(_normalize_adapter_name(name))


def default_langgraph_persistence_registry() -> LangGraphPersistenceRegistry:
    return (
        LangGraphPersistenceRegistry()
        .register_checkpointer("memory", _build_memory_checkpointer)
        .register_checkpointer("sqlite", _build_sqlite_checkpointer)
        .register_checkpointer("postgresql", _build_postgresql_checkpointer)
        .register_checkpointer("mongodb", _build_mongodb_checkpointer)
        .register_checkpointer("custom", _build_custom_checkpointer)
        .register_store("memory", _build_memory_store)
        .register_store("postgresql", _build_postgresql_store)
        .register_store("mongodb", _build_mongodb_store)
        .register_store("redis", _build_redis_store)
        .register_store("custom", _build_custom_store)
    )


def resolve_langgraph_persistence_mode(
    settings: LangGraphPersistenceSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> Literal["embedded", "agent_server"]:
    if settings.mode != "auto":
        return settings.mode

    environment = os.environ if environ is None else environ
    override = environment.get("ARCLITH_LANGGRAPH_PERSISTENCE_MODE")
    if override:
        if override not in {"embedded", "agent_server"}:
            raise ValueError(
                "ARCLITH_LANGGRAPH_PERSISTENCE_MODE doit valoir embedded ou agent_server"
            )
        return cast(Literal["embedded", "agent_server"], override)
    if any(environment.get(marker) for marker in _AGENT_SERVER_MARKERS):
        return "agent_server"
    return "embedded"


def build_langgraph_persistence(
    settings: LangGraphPersistenceSettings,
    *,
    registry: LangGraphPersistenceRegistry | None = None,
    include_checkpointer: bool = True,
    include_store: bool = True,
) -> LangGraphPersistenceComponents:
    mode = resolve_langgraph_persistence_mode(settings)
    components = LangGraphPersistenceComponents(mode=mode)
    if mode == "agent_server":
        return components

    defaults = default_langgraph_persistence_registry()
    try:
        if include_checkpointer and settings.checkpointer.adapter != "none":
            checkpointer_factory = _select_checkpointer_factory(
                settings.checkpointer.adapter, registry, defaults
            )
            created = checkpointer_factory(settings.checkpointer)
            components.checkpointer = _enter_resource(
                components._stack,
                created,
                role="checkpointer",
                adapter=settings.checkpointer.adapter,
            )
            _run_setup(components.checkpointer, settings.checkpointer.setup)

        if include_store and settings.store.adapter != "none":
            store_factory = _select_store_factory(
                settings.store.adapter, registry, defaults
            )
            created = store_factory(settings.store)
            components.store = _enter_resource(
                components._stack,
                created,
                role="store",
                adapter=settings.store.adapter,
            )
            _run_setup(components.store, settings.store.setup)
    except BaseException:
        components.close()
        raise
    return components


def render_langgraph_namespace(
    template: str,
    values: Mapping[str, object],
) -> tuple[str, ...]:
    parts: list[str] = []
    for segment in template.split(":"):
        try:
            rendered = segment.format_map(dict(values)).strip()
        except KeyError as exc:
            missing = exc.args[0]
            raise ValueError(
                f"Valeur de namespace LangGraph manquante: {missing}"
            ) from exc
        if not rendered:
            raise ValueError("Un segment du namespace LangGraph est vide")
        parts.append(rendered)
    return tuple(parts)


def _select_checkpointer_factory(
    adapter: str,
    registry: LangGraphPersistenceRegistry | None,
    defaults: LangGraphPersistenceRegistry,
) -> CheckpointerFactory:
    factory = registry.checkpointer_factory(adapter) if registry is not None else None
    factory = factory or defaults.checkpointer_factory(adapter)
    if factory is None:
        raise ValueError(
            f"Checkpointer LangGraph '{adapter}' non enregistre. "
            "Utilisez LangGraphPersistenceRegistry.register_checkpointer()."
        )
    return factory


def _select_store_factory(
    adapter: str,
    registry: LangGraphPersistenceRegistry | None,
    defaults: LangGraphPersistenceRegistry,
) -> StoreFactory:
    factory = registry.store_factory(adapter) if registry is not None else None
    factory = factory or defaults.store_factory(adapter)
    if factory is None:
        raise ValueError(
            f"Store LangGraph '{adapter}' non enregistre. "
            "Utilisez LangGraphPersistenceRegistry.register_store()."
        )
    return factory


def _enter_resource(
    stack: ExitStack,
    resource: object,
    *,
    role: PersistenceRole,
    adapter: str,
) -> object:
    if resource is None:
        raise TypeError(f"La factory {role} '{adapter}' a retourne None")
    if hasattr(resource, "__aenter__") and not hasattr(resource, "__enter__"):
        raise TypeError(
            f"La factory {role} '{adapter}' retourne un context manager async. "
            "Utilisez un backend synchrone en mode embedded ou configurez l'Agent Server."
        )
    if hasattr(resource, "__enter__") and hasattr(resource, "__exit__"):
        context = cast(AbstractContextManager[object], resource)
        return stack.enter_context(context)
    close = getattr(resource, "close", None)
    if callable(close):
        stack.callback(close)
    return resource


def _run_setup(resource: object | None, enabled: bool) -> None:
    if not enabled or resource is None:
        return
    setup = getattr(resource, "setup", None)
    if not callable(setup):
        return
    result = setup()
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            close()
        raise TypeError(
            "setup() est asynchrone; utilisez un backend synchrone en mode embedded "
            "ou laissez l'Agent Server gerer son cycle de vie."
        )


def _build_memory_checkpointer(settings: LangGraphCheckpointerSettings) -> object:
    _reject_unsupported_ttl(settings, adapter="memory")
    module = _optional_module(
        "langgraph.checkpoint.memory", role="checkpointer", adapter="memory"
    )
    return module.InMemorySaver(**settings.options)


def _build_sqlite_checkpointer(settings: LangGraphCheckpointerSettings) -> object:
    _reject_unsupported_ttl(settings, adapter="sqlite")
    module = _optional_module(
        "langgraph.checkpoint.sqlite", role="checkpointer", adapter="sqlite"
    )
    path = Path(settings.path).expanduser()
    if settings.path != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return module.SqliteSaver.from_conn_string(str(path))


def _build_postgresql_checkpointer(settings: LangGraphCheckpointerSettings) -> object:
    _reject_unsupported_ttl(settings, adapter="postgresql")
    module = _optional_module(
        "langgraph.checkpoint.postgres", role="checkpointer", adapter="postgresql"
    )
    uri = _connection_uri("checkpointer", settings.adapter, settings.connection_uri_env)
    return module.PostgresSaver.from_conn_string(uri, **settings.options)


def _build_mongodb_checkpointer(settings: LangGraphCheckpointerSettings) -> object:
    module = _optional_module(
        "langgraph.checkpoint.mongodb", role="checkpointer", adapter="mongodb"
    )
    uri = _connection_uri("checkpointer", settings.adapter, settings.connection_uri_env)
    options = dict(settings.options)
    options.setdefault("db_name", settings.database)
    if settings.ttl_seconds is not None:
        options.setdefault("ttl", settings.ttl_seconds)
    return module.MongoDBSaver.from_conn_string(uri, **options)


def _build_memory_store(settings: LangGraphStoreSettings) -> object:
    module = _optional_module("langgraph.store.memory", role="store", adapter="memory")
    options = dict(settings.options)
    index = _semantic_index(settings.semantic_search)
    if index is not None:
        options.setdefault("index", index)
    return module.InMemoryStore(**options)


def _build_postgresql_store(settings: LangGraphStoreSettings) -> object:
    module = _optional_module(
        "langgraph.store.postgres", role="store", adapter="postgresql"
    )
    uri = _connection_uri("store", settings.adapter, settings.connection_uri_env)
    options = dict(settings.options)
    index = _semantic_index(settings.semantic_search)
    if index is not None:
        options.setdefault("index", index)
    return module.PostgresStore.from_conn_string(uri, **options)


def _build_mongodb_store(settings: LangGraphStoreSettings) -> object:
    module = _optional_module(
        "langgraph.store.mongodb", role="store", adapter="mongodb"
    )
    uri = _connection_uri("store", settings.adapter, settings.connection_uri_env)
    options = dict(settings.options)
    options.setdefault("db_name", settings.database)
    options.setdefault("collection_name", settings.collection)
    semantic = settings.semantic_search
    if semantic.enabled:
        options.setdefault(
            "index_config",
            module.create_vector_index_config(
                dims=semantic.dims,
                embed=semantic.embed,
                fields=semantic.fields,
            ),
        )
    return module.MongoDBStore.from_conn_string(uri, **options)


def _build_redis_store(settings: LangGraphStoreSettings) -> object:
    module = _optional_module("langgraph.store.redis", role="store", adapter="redis")
    uri = _connection_uri("store", settings.adapter, settings.connection_uri_env)
    options = dict(settings.options)
    index = _semantic_index(settings.semantic_search)
    if index is not None:
        options.setdefault("index", index)
    return module.RedisStore.from_conn_string(uri, **options)


def _build_custom_checkpointer(settings: LangGraphCheckpointerSettings) -> object:
    factory = _import_factory(settings.factory, role="checkpointer")
    return factory(settings)


def _build_custom_store(settings: LangGraphStoreSettings) -> object:
    factory = _import_factory(settings.factory, role="store")
    return factory(settings)


def _import_factory(
    path: str | None,
    *,
    role: PersistenceRole,
) -> Callable[[Any], object]:
    if not path or ":" not in path:
        raise ValueError(
            f"{role}.factory doit utiliser le format 'package.module:factory' "
            "quand adapter=custom"
        )
    module_name, attribute = path.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise TypeError(f"La factory {role} '{path}' est introuvable ou non appelable")
    return factory


def _connection_uri(
    role: PersistenceRole,
    adapter: str,
    configured_env: str | None,
) -> str:
    env_name = configured_env or _DEFAULT_CONNECTION_ENV.get((role, adapter))
    if env_name is None:
        raise ValueError(
            f"Aucune variable de connexion par defaut pour {role}={adapter}"
        )
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(
            f"Variable d'environnement {env_name} requise pour le {role} LangGraph '{adapter}'. "
            "Injectez-la au runtime ou configurez connection_uri_env."
        )
    return value


def _semantic_index(
    settings: LangGraphSemanticSearchSettings,
) -> dict[str, object] | None:
    if not settings.enabled:
        return None
    return {
        "embed": cast(str, settings.embed),
        "dims": cast(int, settings.dims),
        "fields": list(settings.fields),
    }


def _optional_module(
    module_name: str,
    *,
    role: PersistenceRole,
    adapter: str,
) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        extra = _EXTRA_BY_BACKEND[(role, adapter)]
        raise RuntimeError(
            f"Backend LangGraph {role} '{adapter}' non installe. "
            f"Installez `arclith[{extra}]`."
        ) from exc


def _reject_unsupported_ttl(
    settings: LangGraphCheckpointerSettings,
    *,
    adapter: str,
) -> None:
    if settings.ttl_seconds is not None:
        raise ValueError(
            f"ttl_seconds n'est pas supporte par le checkpointer embedded '{adapter}'. "
            "Utilisez MongoDB, un backend custom ou la configuration Agent Server."
        )


def _normalize_adapter_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Le nom d'un backend LangGraph ne doit pas etre vide")
    return normalized
