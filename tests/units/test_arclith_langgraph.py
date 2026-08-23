from typing import Any, TypedDict

import pytest

from arclith import Arclith

langgraph_graph = pytest.importorskip("langgraph.graph")
END = langgraph_graph.END
START = langgraph_graph.START


class AgentState(TypedDict, total=False):
    value: str


def test_langgraph_builds_compiled_graph(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    arclith = Arclith(config_dir)
    registered: dict[str, Arclith] = {}

    def register_agent(builder: Any, current_arclith: Arclith) -> None:
        registered["arclith"] = current_arclith

        def echo(state: AgentState) -> AgentState:
            return {"value": f"{state.get('value', '')}!"}

        builder.add_node("echo", echo)
        builder.add_edge(START, "echo")
        builder.add_edge("echo", END)

    agent = arclith.langgraph(AgentState, register_agent, name="test_agent")

    assert registered["arclith"] is arclith
    assert agent.invoke({"value": "ok"}) == {"value": "ok!"}


def test_langgraph_applies_stream_mode_from_config(tmp_path):
    config_dir = tmp_path / "config"
    langgraph_config = config_dir / "adapters" / "inbound" / "langgraph.yaml"
    langgraph_config.parent.mkdir(parents=True)
    langgraph_config.write_text(
        """
entrypoint: "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"
stream_mode:
  - updates
  - custom
""",
        encoding="utf-8",
    )
    arclith = Arclith(config_dir)

    def register_agent(builder: Any, current_arclith: Arclith) -> None:
        def echo(state: AgentState) -> AgentState:
            return state

        builder.add_node("echo", echo)
        builder.add_edge(START, "echo")
        builder.add_edge("echo", END)

    agent = arclith.langgraph(AgentState, register_agent, name="test_agent")

    assert agent.stream_mode == ["updates", "custom"]


def test_langgraph_stream_mode_argument_overrides_config(tmp_path):
    config_dir = tmp_path / "config"
    langgraph_config = config_dir / "adapters" / "inbound" / "langgraph.yaml"
    langgraph_config.parent.mkdir(parents=True)
    langgraph_config.write_text(
        """
entrypoint: "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"
stream_mode: "updates"
""",
        encoding="utf-8",
    )
    arclith = Arclith(config_dir)

    def register_agent(builder: Any, current_arclith: Arclith) -> None:
        def echo(state: AgentState) -> AgentState:
            return state

        builder.add_node("echo", echo)
        builder.add_edge(START, "echo")
        builder.add_edge("echo", END)

    agent = arclith.langgraph(AgentState, register_agent, name="test_agent", stream_mode="values")

    assert agent.stream_mode == "values"
