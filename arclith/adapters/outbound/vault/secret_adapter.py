from __future__ import annotations

import os
from pathlib import Path

from arclith.domain.ports.outbound.secret_resolver import SecretResolver


def _read_vault_token() -> str | None:
    token = os.environ.get("VAULT_TOKEN")
    if token:
        return token
    token_file = Path.home() / ".vault-token"
    if token_file.exists():
        return token_file.read_text().strip() or None
    return None


class VaultSecretAdapter(SecretResolver):
    """Reads secrets from HashiCorp Vault KV v2.

    Each secret_key is a Vault path relative to the mount point.
    The secret must expose its value under the field "value".

    Example:
        vault kv put kv/rekipe/recipe/mongodb value="mongodb://..."
    """

    def __init__(self, addr: str, mount: str = "kv") -> None:
        self._addr = addr
        self._mount = mount

    def get(self, field_path: str, secret_key: str) -> str | None:
        try:
            import hvac  # type: ignore[import-untyped]
        except ImportError:
            return None

        token = _read_vault_token()
        if not token:
            return None

        try:
            client = hvac.Client(url=self._addr, token=token)
            if not client.is_authenticated():
                return None
            response = client.secrets.kv.v2.read_secret_version(
                path=secret_key,
                mount_point=self._mount,
                raise_on_deleted_version=True,
            )
            return response["data"]["data"].get("value")
        except Exception:
            return None

