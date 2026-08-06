from arclith.domain.ports.outbound.llm import LLMPort


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
