from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Callable, ContextManager

TraceAnonymizer = Callable[[dict[str, Any]], dict[str, Any]]


class TraceSpan(ABC):
    """Provider-neutral handle for a span created at an application boundary."""

    @abstractmethod
    def set_outputs(self, outputs: object | None) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        raise NotImplementedError


class TracePort(ABC):
    """Outbound tracing contract with a no-op implementation available by default."""

    @abstractmethod
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> ContextManager[TraceSpan]:
        raise NotImplementedError

    @abstractmethod
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> ContextManager[None]:
        raise NotImplementedError

    @abstractmethod
    def inject(self, headers: MutableMapping[str, str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def flush(self, timeout: float | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self, timeout: float | None = None) -> None:
        raise NotImplementedError

    def diagnostics(self) -> Mapping[str, Any]:
        return {}
