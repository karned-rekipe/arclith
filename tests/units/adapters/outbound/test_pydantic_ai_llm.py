from types import SimpleNamespace

import pydantic_ai

from arclith.adapters.outbound.pydantic_ai import llm as llm_module
from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter
from arclith.domain.ports.outbound.llm import (
    LLMPort,
    LLMStructuredChunk,
    LLMStructuredFinal,
    LLMStructuredStreamOptions,
)
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


def test_pydantic_ai_llm_adapter_scopes_instrumentation_to_built_agent(
    monkeypatch,
) -> None:
    instrumentation = object()
    seen: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, model, **kwargs) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(
        llm_module, "build_pydantic_ai_model", lambda settings: object()
    )
    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        ),
        instrumentation=instrumentation,
    )

    adapter._build_agent(output_type=dict, instructions="instructions")

    assert seen["capabilities"] == [instrumentation]


async def test_pydantic_ai_llm_adapter_returns_structured_output(monkeypatch) -> None:
    class Result:
        pass

    class FakeAgent:
        def __init__(self, model, *, output_type, instructions) -> None:
            self._output_type = output_type

        async def run(self, prompt: str):
            return SimpleNamespace(output=self._output_type())

    monkeypatch.setattr(
        llm_module, "build_pydantic_ai_model", lambda settings: object()
    )
    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    result = await adapter.complete_structured(
        "prompt", output_type=Result, instructions="instructions"
    )

    assert isinstance(result, Result)


async def test_pydantic_ai_llm_adapter_streams_structured_output(monkeypatch) -> None:
    class Result:
        def __init__(self, value: str = "") -> None:
            self.value = value

    seen: dict[str, object] = {}

    class FakeStreamResult:
        def __init__(self, output_type) -> None:
            self._output_type = output_type
            self._final = output_type("final")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def stream_output(self, *, debounce_by: float | None = 0.1):
            seen["debounce_by"] = debounce_by
            yield self._output_type("partial")

        def get_output(self):
            return self._final

    class FakeAgent:
        def __init__(self, model, *, output_type, instructions) -> None:
            self._output_type = output_type
            seen["instructions"] = instructions

        def run_stream(self, prompt: str):
            seen["prompt"] = prompt
            return FakeStreamResult(self._output_type)

    monkeypatch.setattr(
        llm_module, "build_pydantic_ai_model", lambda settings: object()
    )
    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    events = [
        event
        async for event in adapter.stream_structured(
            "prompt",
            output_type=Result,
            instructions="instructions",
            stream_options=LLMStructuredStreamOptions(debounce_by=None),
        )
    ]

    assert seen == {
        "instructions": "instructions",
        "prompt": "prompt",
        "debounce_by": None,
    }
    assert [event.kind for event in events] == [
        "progress",
        "progress",
        "structured_chunk",
        "progress",
        "structured_final",
    ]
    assert isinstance(events[2], LLMStructuredChunk)
    assert events[2].sequence == 1
    assert events[2].output.value == "partial"
    assert isinstance(events[-1], LLMStructuredFinal)
    assert events[-1].output.value == "final"
    assert events[-1].metadata["snapshots"] == 1


async def test_pydantic_ai_llm_adapter_can_disable_stream_snapshots(
    monkeypatch,
) -> None:
    class Result:
        pass

    seen: dict[str, bool] = {"run_stream": False}

    class FakeAgent:
        def __init__(self, model, *, output_type, instructions) -> None:
            self._output_type = output_type

        async def run(self, prompt: str):
            return SimpleNamespace(output=self._output_type())

        def run_stream(self, prompt: str):
            seen["run_stream"] = True
            raise AssertionError(
                "run_stream should not be called when snapshots are disabled"
            )

    monkeypatch.setattr(
        llm_module, "build_pydantic_ai_model", lambda settings: object()
    )
    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    adapter = PydanticAILLMAdapter(
        LMSettings(
            provider="openai",
            model_name="local-model",
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    events = [
        event
        async for event in adapter.stream_structured(
            "prompt",
            output_type=Result,
            instructions="instructions",
            stream_options=LLMStructuredStreamOptions(
                include_progress=False, include_snapshots=False
            ),
        )
    ]

    assert seen["run_stream"] is False
    assert len(events) == 1
    assert isinstance(events[0], LLMStructuredFinal)
    assert isinstance(events[0].output, Result)
