from __future__ import annotations

import os
from pathlib import Path

from arclith.domain.ports.outbound.secret_resolver import SecretResolver


def build_secret_resolver(raw_config: dict, base_path: Path | None = None) -> SecretResolver | None:
    """Build a SecretResolver from raw config dict (before Pydantic validation).

    Returns None when no mappings are declared (nothing to resolve).
    VAULT_ADDR env var overrides secrets.vault.addr from config.
    """
    secrets = raw_config.get("secrets") or {}
    mappings: dict = secrets.get("mappings") or {}
    if not mappings:
        return None

    resolver_type: str = secrets.get("resolver", "yaml")

    def _make(name: str) -> SecretResolver:
        match name:
            case "vault":
                vault_cfg: dict = secrets.get("vault") or {}
                addr = os.environ.get("VAULT_ADDR") or vault_cfg.get("addr", "http://127.0.0.1:8200")
                mount: str = vault_cfg.get("mount", "kv")
                from arclith.adapters.outbound.vault.secret_adapter import VaultSecretAdapter
                return VaultSecretAdapter(addr=addr, mount=mount)
            case "yaml":
                yaml_cfg: dict = secrets.get("yaml") or {}
                default_path = str(base_path / "secrets.yaml") if base_path else "secrets.yaml"
                path: str = yaml_cfg.get("path", default_path)
                from arclith.adapters.outbound.yaml.secret_adapter import YamlSecretAdapter
                return YamlSecretAdapter(path=path)
            case "env":
                from arclith.adapters.outbound.env.secret_adapter import EnvSecretAdapter
                return EnvSecretAdapter()
            case _:
                raise ValueError(f"Unknown secret resolver: '{name}'")

    if resolver_type == "chain":
        chain_names: list[str] = secrets.get("chain") or ["yaml"]
        from arclith.adapters.outbound.chain.secret_adapter import ChainSecretAdapter
        return ChainSecretAdapter([_make(n) for n in chain_names])

    return _make(resolver_type)

