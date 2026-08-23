from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from arclith.domain.ports.outbound.llm import (
    LLMPort,
    LLMProgressEvent,
    LLMStructuredFinal,
    LLMStructuredStreamOptions,
    llm_stream_event_to_payload,
)


class StaticLLM(LLMPort):
    async def complete_structured[T](
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
    ) -> T:
        return output_type()


async def test_llm_port_supports_typed_structured_completion() -> None:
    class Result:
        pass

    llm = StaticLLM()

    result = await llm.complete_structured("prompt", output_type=Result, instructions="instructions")

    assert isinstance(result, Result)


async def test_llm_port_streams_progress_and_final_object_by_default() -> None:
    class Result:
        pass

    llm = StaticLLM()

    events = [
        event
        async for event in llm.stream_structured("prompt", output_type=Result, instructions="instructions")
    ]

    assert isinstance(events[0], LLMProgressEvent)
    assert events[0].stage == "llm.started"
    assert isinstance(events[1], LLMStructuredFinal)
    assert isinstance(events[1].output, Result)


async def test_llm_port_stream_options_can_disable_progress() -> None:
    class Result:
        pass

    llm = StaticLLM()

    events = [
        event
        async for event in llm.stream_structured(
            "prompt",
            output_type=Result,
            instructions="instructions",
            stream_options=LLMStructuredStreamOptions(include_progress=False),
        )
    ]

    assert len(events) == 1
    assert isinstance(events[0], LLMStructuredFinal)


def test_llm_stream_event_payload_serializes_structured_outputs() -> None:
    class PydanticResult(BaseModel):
        title: str

    @dataclass(frozen=True)
    class DataclassResult:
        title: str

    assert llm_stream_event_to_payload(LLMStructuredFinal(output=PydanticResult(title="pydantic"))) == {
        "kind": "structured_final",
        "output": {"title": "pydantic"},
        "metadata": {},
    }
    assert llm_stream_event_to_payload(LLMStructuredFinal(output=DataclassResult(title="dataclass"))) == {
        "kind": "structured_final",
        "output": {"title": "dataclass"},
        "metadata": {},
    }


def test_llm_stream_options_reject_negative_debounce() -> None:
    with pytest.raises(ValueError, match="debounce_by must be >= 0 or None"):
        LLMStructuredStreamOptions(debounce_by=-0.1)
