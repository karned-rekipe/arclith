from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from types import MappingProxyType
from typing import Any, Literal, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class LLMStructuredStreamOptions:
    """Options for structured LLM streaming."""

    include_progress: bool = True
    include_snapshots: bool = True
    debounce_by: float | None = 0.1

    def __post_init__(self) -> None:
        if self.debounce_by is not None and self.debounce_by < 0:
            raise ValueError("debounce_by must be >= 0 or None")


@dataclass(frozen=True)
class LLMProgressEvent:
    """Provider-neutral progress event emitted during a structured LLM run."""

    stage: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    kind: Literal["progress"] = "progress"

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class LLMStructuredChunk[T]:
    """Accumulated, partially validated structured output snapshot."""

    output: T
    sequence: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    kind: Literal["structured_chunk"] = "structured_chunk"

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("sequence must be > 0")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class LLMStructuredFinal[T]:
    """Final structured output for a completed LLM run."""

    output: T
    metadata: Mapping[str, Any] = field(default_factory=dict)
    kind: Literal["structured_final"] = "structured_final"

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


type LLMStreamEvent[T] = LLMProgressEvent | LLMStructuredChunk[T] | LLMStructuredFinal[T]


def llm_stream_event_to_payload(event: LLMStreamEvent[Any]) -> dict[str, Any]:
    """Convert an LLM stream event into a JSON-friendly payload."""
    if isinstance(event, LLMProgressEvent):
        return {
            "kind": event.kind,
            "stage": event.stage,
            "message": event.message,
            "metadata": dict(event.metadata),
        }
    if isinstance(event, LLMStructuredChunk):
        return {
            "kind": event.kind,
            "sequence": event.sequence,
            "output": _serialize_output(event.output),
            "metadata": dict(event.metadata),
        }
    return {
        "kind": event.kind,
        "output": _serialize_output(event.output),
        "metadata": dict(event.metadata),
    }


def _serialize_output(output: Any) -> Any:
    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if is_dataclass(output) and not isinstance(output, type):
        return asdict(output)
    return output


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

    async def stream_structured(
        self,
        prompt: str,
        *,
        output_type: type[T],
        instructions: str,
        stream_options: LLMStructuredStreamOptions | None = None,
    ) -> AsyncIterator[LLMStreamEvent[T]]:
        """Stream progress and structured output while preserving the final object contract."""
        options = stream_options or LLMStructuredStreamOptions()
        if options.include_progress:
            yield LLMProgressEvent(
                stage="llm.started",
                message="Structured completion started.",
            )

        output = await self.complete_structured(
            prompt,
            output_type=output_type,
            instructions=instructions,
        )
        yield LLMStructuredFinal(output=output)
