from abc import ABC, abstractmethod
from typing import TypeVar

T = TypeVar("T")


class LLMPort(ABC):
    @abstractmethod
    async def complete_structured(
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
    ) -> T:
        """Transform a natural-language prompt into a typed structured object."""
        ...
