from types import SimpleNamespace

import pydantic_ai

from arclith.adapters.outbound.pydantic_ai import llm as llm_module
from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter
from arclith.domain.ports.outbound.llm import LLMPort
from arclith.infrastructure.config import LMSettings


def test_pydantic_ai_llm_adapter_implements_llm_port() -> None:
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    assert isinstance(adapter, LLMPort)


async def test_pydantic_ai_llm_adapter_returns_structured_output(monkeypatch) -> None:
    class Result:
        pass

    class FakeAgent:
        def __init__(self, model, *, output_type, instructions) -> None:
            self._output_type = output_type

        async def run(self, prompt: str):
            return SimpleNamespace(output=self._output_type())

    monkeypatch.setattr(llm_module, "build_pydantic_ai_model", lambda settings: object())
    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    result = await adapter.complete_structured("prompt", output_type=Result, instructions="instructions")

    assert isinstance(result, Result)
