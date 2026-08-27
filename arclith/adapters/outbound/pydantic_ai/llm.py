from collections.abc import AsyncIterator
from typing import Any
from typing import TypeVar

from arclith.domain.ports.outbound.llm import (
    LLMPort,
    LLMProgressEvent,
    LLMStreamEvent,
    LLMStructuredChunk,
    LLMStructuredFinal,
    LLMStructuredStreamOptions,
)
from arclith.infrastructure.config import LMSettings
from arclith.infrastructure.lm import build_pydantic_ai_model

T = TypeVar("T")


class PydanticAILLMAdapter(LLMPort):
    def __init__(
        self, settings: LMSettings, *, instrumentation: Any | None = None
    ) -> None:
        self._settings = settings
        self._instrumentation = instrumentation

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
    ) -> T:
        agent = self._build_agent(output_type=output_type, instructions=instructions)
        result = await agent.run(prompt)
        return result.output

    async def stream_structured(
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
        stream_options: LLMStructuredStreamOptions | None = None,
    ) -> AsyncIterator[LLMStreamEvent[T]]:
        options = stream_options or LLMStructuredStreamOptions()
        agent = self._build_agent(output_type=output_type, instructions=instructions)

        if options.include_progress:
            yield LLMProgressEvent(
                stage="llm.started",
                message="Structured completion started.",
            )

        if not options.include_snapshots:
            result = await agent.run(prompt)
            yield LLMStructuredFinal(output=result.output)
            return

        sequence = 0
        async with agent.run_stream(prompt) as result:
            if options.include_progress:
                yield LLMProgressEvent(
                    stage="llm.streaming",
                    message="Structured output stream opened.",
                )

            async for output in result.stream_output(debounce_by=options.debounce_by):
                sequence += 1
                yield LLMStructuredChunk(output=output, sequence=sequence)

            final_output = result.get_output()

        if options.include_progress:
            yield LLMProgressEvent(
                stage="llm.completed",
                message="Structured completion finished.",
                metadata={"snapshots": sequence},
            )
        yield LLMStructuredFinal(output=final_output, metadata={"snapshots": sequence})

    def _build_agent(
        self,
        *,
        output_type: type[T],
        instructions: str,
    ) -> Any:
        from pydantic_ai import Agent

        kwargs: dict[str, Any] = {
            "output_type": output_type,
            "instructions": instructions,
        }
        if self._instrumentation is not None:
            kwargs["capabilities"] = [self._instrumentation]
        return Agent(build_pydantic_ai_model(self._settings), **kwargs)
