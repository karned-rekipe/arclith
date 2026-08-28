from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, MessagesState, StateGraph


def _last_content(messages: list[BaseMessage]) -> str:
    return str(messages[-1].content) if messages else ""


async def respond(state: MessagesState) -> dict[str, Any]:
    return {
        "messages": [
            AIMessage(content=f"Echo: {_last_content(state.get('messages', []))}")
        ]
    }


builder = StateGraph(MessagesState)
builder.add_node("respond", respond)
builder.add_edge(START, "respond")
builder.add_edge("respond", END)
graph = builder.compile()
