from typing import TypeVar

from arclith.domain.ports.outbound.llm import LLMPort
from arclith.infrastructure.config import LMSettings
from arclith.infrastructure.lm import build_pydantic_ai_model

T = TypeVar("T")


class PydanticAILLMAdapter(LLMPort):
    def __init__(self, settings: LMSettings) -> None:
        self._settings = settings

    async def complete_structured(
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
    ) -> T:
        from pydantic_ai import Agent

        agent = Agent(
            build_pydantic_ai_model(self._settings),
            output_type=output_type,
            instructions=instructions,
        )
        result = await agent.run(prompt)
        return result.output
