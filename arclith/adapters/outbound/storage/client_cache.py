from collections.abc import Callable
from typing import Any


class StorageClientCache:
    """Cache a single default SDK client while keeping tenant-specific clients isolated."""

    def __init__(self, injected_client: Any | None) -> None:
        self._injected_client = injected_client
        self._default_client: Any | None = None

    def get(self, *, multitenant: bool, create_client: Callable[[], Any]) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        if multitenant:
            return create_client()
        if self._default_client is None:
            self._default_client = create_client()
        return self._default_client
