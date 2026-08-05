from typing import Any, TypedDict

from langgraph.graph import END, START

from arclith import Arclith


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
