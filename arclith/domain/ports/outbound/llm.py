from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import PurePath
from types import MappingProxyType
from typing import Any, Literal, TypeVar
from uuid import UUID

T = TypeVar("T")
_UNHANDLED = object()


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
            "metadata": _serialize_output(event.metadata),
        }
    if isinstance(event, LLMStructuredChunk):
        return {
            "kind": event.kind,
            "sequence": event.sequence,
            "output": _serialize_output(event.output),
            "metadata": _serialize_output(event.metadata),
        }
    return {
        "kind": event.kind,
        "output": _serialize_output(event.output),
        "metadata": _serialize_output(event.metadata),
    }


def _serialize_output(output: Any) -> Any:
    if output is None or isinstance(output, str | int | float | bool):
        return output

    for serializer in _OUTPUT_SERIALIZERS:
        serialized = serializer(output)
        if serialized is not _UNHANDLED:
            return serialized

    return str(output)


def _serialize_model_dump(output: Any) -> Any:
    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return _UNHANDLED


def _serialize_dataclass(output: Any) -> Any:
    if is_dataclass(output) and not isinstance(output, type):
        return _serialize_output(asdict(output))
    return _UNHANDLED


def _serialize_enum(output: Any) -> Any:
    if isinstance(output, Enum):
        return _serialize_output(output.value)
    return _UNHANDLED


def _serialize_temporal(output: Any) -> Any:
    if isinstance(output, datetime | date | time):
        return output.isoformat()
    return _UNHANDLED


def _serialize_stringlike(output: Any) -> Any:
    if isinstance(output, UUID | PurePath):
        return str(output)
    return _UNHANDLED


def _serialize_mapping(output: Any) -> Any:
    if isinstance(output, Mapping):
        return {str(key): _serialize_output(value) for key, value in output.items()}
    return _UNHANDLED


def _serialize_sequence(output: Any) -> Any:
    if isinstance(output, list | tuple | set | frozenset):
        return [_serialize_output(item) for item in output]
    return _UNHANDLED


_OUTPUT_SERIALIZERS = (
    _serialize_model_dump,
    _serialize_dataclass,
    _serialize_enum,
    _serialize_temporal,
    _serialize_stringlike,
    _serialize_mapping,
    _serialize_sequence,
)


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
