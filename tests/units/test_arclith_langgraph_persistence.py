from __future__ import annotations

from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

import pytest

from arclith import Arclith

langgraph_graph = pytest.importorskip("langgraph.graph")
langgraph_memory = pytest.importorskip("langgraph.checkpoint.memory")
langgraph_store = pytest.importorskip("langgraph.store.memory")
END = langgraph_graph.END
START = langgraph_graph.START
InMemorySaver = langgraph_memory.InMemorySaver
InMemoryStore = langgraph_store.InMemoryStore


class ConversationState(TypedDict):
    messages: Annotated[list[str], add]


def _write_config(tmp_path: Path, *, mode: str = "embedded") -> Path:
    config_dir = tmp_path / "config"
    langgraph_config = config_dir / "adapters" / "inbound" / "langgraph.yaml"
    langgraph_config.parent.mkdir(parents=True)
    langgraph_config.write_text(
        f"""entrypoint: "./src/app/adapters/inbound/langgraph/agent.py:agent"
persistence:
  enabled: true
  mode: {mode}
  checkpointer:
    adapter: memory
  store:
    adapter: memory
    namespace_template: "{{tenant_id}}:{{user_id}}:memories"
""",
        encoding="utf-8",
    )
    return config_dir


def _register_graph(builder: Any, _arclith: Arclith) -> None:
    builder.add_node("pass_through", lambda _state: {})
    builder.add_edge(START, "pass_through")
    builder.add_edge("pass_through", END)


def test_memory_checkpointer_keeps_state_for_same_thread(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path))
    agent = arclith.langgraph(ConversationState, _register_graph)
    config = {"configurable": {"thread_id": "thread-stable-1"}}

    first = agent.invoke({"messages": ["first"]}, config)
    second = agent.invoke({"messages": ["second"]}, config)

    assert first["messages"] == ["first"]
    assert second["messages"] == ["first", "second"]
    arclith.close_langgraph_persistence()


def test_sqlite_checkpointer_recovers_thread_after_graph_rebuild(
    tmp_path: Path,
) -> None:
    pytest.importorskip("langgraph.checkpoint.sqlite")
    config_dir = tmp_path / "config"
    checkpoint_path = tmp_path / "state" / "checkpoints.sqlite"
    langgraph_config = config_dir / "adapters" / "inbound" / "langgraph.yaml"
    langgraph_config.parent.mkdir(parents=True)
    langgraph_config.write_text(
        f'''entrypoint: "./src/app/adapters/inbound/langgraph/agent.py:agent"
persistence:
  enabled: true
  mode: embedded
  checkpointer:
    adapter: sqlite
    path: "{checkpoint_path}"
    setup: true
  store:
    adapter: none
''',
        encoding="utf-8",
    )
    thread_config = {"configurable": {"thread_id": "stable-local-thread"}}

    first_arclith = Arclith(config_dir)
    first_agent = first_arclith.langgraph(ConversationState, _register_graph)
    first_agent.invoke({"messages": ["first"]}, thread_config)
    first_arclith.close_langgraph_persistence()

    second_arclith = Arclith(config_dir)
    second_agent = second_arclith.langgraph(ConversationState, _register_graph)
    recovered = second_agent.invoke({"messages": ["second"]}, thread_config)

    assert recovered["messages"] == ["first", "second"]
    second_arclith.close_langgraph_persistence()


def test_memory_store_is_shared_across_threads(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path))
    agent = arclith.langgraph(ConversationState, _register_graph, persistence=True)
    namespace = arclith.langgraph_memory_namespace(
        tenant_id="tenant-a", user_id="user-42"
    )

    agent.invoke(
        {"messages": ["remember dark mode"]},
        {"configurable": {"thread_id": "thread-a"}},
    )
    agent.store.put(namespace, "theme", {"value": "dark"})
    agent.invoke(
        {"messages": ["new conversation"]},
        {"configurable": {"thread_id": "thread-b"}},
    )

    assert agent.store.get(namespace, "theme").value == {"value": "dark"}
    arclith.close_langgraph_persistence()


def test_explicit_checkpointer_and_store_override_yaml(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path))
    explicit_checkpointer = InMemorySaver()
    explicit_store = InMemoryStore()

    agent = arclith.langgraph(
        ConversationState,
        _register_graph,
        persistence=True,
        checkpointer=explicit_checkpointer,
        store=explicit_store,
    )

    assert agent.checkpointer is explicit_checkpointer
    assert agent.store is explicit_store
    assert "_langgraph_persistence_resources" not in arclith.__dict__


def test_explicit_component_only_overrides_its_configured_role(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path))
    explicit_checkpointer = InMemorySaver()

    agent = arclith.langgraph(
        ConversationState,
        _register_graph,
        persistence=True,
        checkpointer=explicit_checkpointer,
    )

    assert agent.checkpointer is explicit_checkpointer
    assert agent.store.__class__.__name__ == "InMemoryStore"
    arclith.close_langgraph_persistence()


def test_persistence_false_disables_framework_injection(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path))

    agent = arclith.langgraph(
        ConversationState,
        _register_graph,
        persistence=False,
    )

    assert agent.checkpointer is None
    assert agent.store is None


def test_agent_server_mode_leaves_persistence_to_server(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path, mode="agent_server"))

    agent = arclith.langgraph(
        ConversationState,
        _register_graph,
        persistence=True,
    )

    assert agent.checkpointer is None
    assert agent.store is None
    assert "_langgraph_persistence_resources" not in arclith.__dict__


def test_persistence_true_requires_enabled_configuration(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    arclith = Arclith(config_dir)

    with pytest.raises(RuntimeError, match="persistence.enabled=true"):
        arclith.langgraph(
            ConversationState,
            _register_graph,
            persistence=True,
        )
