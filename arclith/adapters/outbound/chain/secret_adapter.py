from __future__ import annotations

from arclith.domain.ports.outbound.secret_resolver import SecretResolver


class ChainSecretAdapter(SecretResolver):
    """Tries each adapter in order, returns the first non-None value.

    Example chain: [VaultSecretAdapter, YamlSecretAdapter]
    → tries Vault first, falls back to secrets.yaml if Vault is unreachable.
    """

    def __init__(self, adapters: list[SecretResolver]) -> None:
        self._adapters = adapters

    def get(self, field_path: str, secret_key: str) -> str | None:
        for adapter in self._adapters:
            value = adapter.get(field_path, secret_key)
            if value is not None:
                return value
        return None

