from __future__ import annotations

from pathlib import Path

import pytest

from arclith.infrastructure.secret_factory import build_secret_resolver
from arclith.infrastructure.secret_loader import resolve_dict_secrets


# ── build_secret_resolver ─────────────────────────────────────────────────────

def test_returns_none_when_no_secrets_section() -> None:
    assert build_secret_resolver({}) is None


def test_returns_none_when_empty_mappings() -> None:
    assert build_secret_resolver({"secrets": {"mappings": {}}}) is None


def test_builds_yaml_resolver(tmp_path: Path) -> None:
    (tmp_path / "secrets.yaml").write_text("")
    data = {
        "secrets": {
            "resolver": "yaml",
            "mappings": {"adapters.mongodb.uri": "ignored"},
            "yaml": {"path": "secrets.yaml"},
        }
    }
    from arclith.adapters.outbound.yaml.secret_adapter import YamlSecretAdapter
    assert isinstance(build_secret_resolver(data), YamlSecretAdapter)


def test_yaml_resolver_defaults_to_secrets_yaml(tmp_path: Path) -> None:
    (tmp_path / "secrets.yaml").write_text("")
    data = {
        "secrets": {
            "resolver": "yaml",
            "mappings": {"adapters.mongodb.uri": "ignored"},
        }
    }
    from arclith.adapters.outbound.yaml.secret_adapter import YamlSecretAdapter
    assert isinstance(build_secret_resolver(data, tmp_path), YamlSecretAdapter)


def test_builds_env_resolver() -> None:
    data = {
        "secrets": {
            "resolver": "env",
            "mappings": {"adapters.mongodb.uri": "ignored"},
        }
    }
    from arclith.adapters.outbound.env.secret_adapter import EnvSecretAdapter
    assert isinstance(build_secret_resolver(data), EnvSecretAdapter)


def test_builds_vault_resolver() -> None:
    data = {
        "secrets": {
            "resolver": "vault",
            "mappings": {"adapters.mongodb.uri": "ignored"},
            "vault": {"addr": "http://127.0.0.1:8200", "mount": "kv"},
        }
    }
    from arclith.adapters.outbound.vault.secret_adapter import VaultSecretAdapter
    assert isinstance(build_secret_resolver(data), VaultSecretAdapter)


def test_vault_addr_overridden_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_ADDR", "http://custom:9999")
    data = {
        "secrets": {
            "resolver": "vault",
            "mappings": {"x": "y"},
            "vault": {"addr": "http://127.0.0.1:8200"},
        }
    }
    from arclith.adapters.outbound.vault.secret_adapter import VaultSecretAdapter
    resolver = build_secret_resolver(data)
    assert isinstance(resolver, VaultSecretAdapter)
    assert resolver._addr == "http://custom:9999"


def test_builds_chain_resolver() -> None:
    data = {
        "secrets": {
            "resolver": "chain",
            "chain": ["env"],
            "mappings": {"adapters.mongodb.uri": "ignored"},
        }
    }
    from arclith.adapters.outbound.chain.secret_adapter import ChainSecretAdapter
    assert isinstance(build_secret_resolver(data), ChainSecretAdapter)


def test_chain_defaults_to_yaml_when_no_chain_key(tmp_path: Path) -> None:
    (tmp_path / "secrets.yaml").write_text("")
    data = {
        "secrets": {
            "resolver": "chain",
            "mappings": {"x": "y"},
        }
    }
    from arclith.adapters.outbound.chain.secret_adapter import ChainSecretAdapter
    assert isinstance(build_secret_resolver(data, tmp_path), ChainSecretAdapter)


def test_unknown_resolver_raises() -> None:
    data = {
        "secrets": {
            "resolver": "unknown",
            "mappings": {"x": "y"},
        }
    }
    with pytest.raises(ValueError, match="Unknown secret resolver"):
        build_secret_resolver(data)


# ── resolve_dict_secrets ──────────────────────────────────────────────────────

def _make_resolver(values: dict[str, str | None]):
    from arclith.domain.ports.outbound.secret_resolver import SecretResolver

    class _Fixed(SecretResolver):
        def get(self, field_path: str, secret_key: str) -> str | None:
            return values.get(field_path)

    return _Fixed()


def test_resolve_injects_value() -> None:
    data = {
        "adapters": {"mongodb": {}},
        "secrets": {"mappings": {"adapters.mongodb.uri": "some/path"}},
    }
    resolver = _make_resolver({"adapters.mongodb.uri": "mongodb://injected:5971"})
    result = resolve_dict_secrets(data, resolver)
    assert result["adapters"]["mongodb"]["uri"] == "mongodb://injected:5971"


def test_resolve_does_not_mutate_original() -> None:
    data = {
        "adapters": {"mongodb": {}},
        "secrets": {"mappings": {"adapters.mongodb.uri": "p"}},
    }
    resolver = _make_resolver({"adapters.mongodb.uri": "new-uri"})
    resolve_dict_secrets(data, resolver)
    assert "uri" not in data["adapters"]["mongodb"]


def test_resolve_no_mappings_returns_original() -> None:
    data = {"adapters": {"mongodb": {}}}
    resolver = _make_resolver({})
    assert resolve_dict_secrets(data, resolver) is data


def test_resolve_raises_on_unresolved_secret() -> None:
    data = {"secrets": {"mappings": {"adapters.mongodb.uri": "p"}}}
    resolver = _make_resolver({"adapters.mongodb.uri": None})
    with pytest.raises(RuntimeError, match="adapters.mongodb.uri"):
        resolve_dict_secrets(data, resolver)


def test_resolve_keeps_null_placeholder_when_secret_is_unresolved() -> None:
    data = {
        "adapters": {"mongodb": {"uri": None, "db_name": "fallback"}},
        "secrets": {"mappings": {"adapters.mongodb.uri": "MONGODB_URI"}},
    }
    resolver = _make_resolver({"adapters.mongodb.uri": None})

    result = resolve_dict_secrets(data, resolver)

    assert result["adapters"]["mongodb"]["uri"] is None
    assert result["adapters"]["mongodb"]["db_name"] == "fallback"


def test_resolve_creates_intermediate_dicts() -> None:
    data = {"secrets": {"mappings": {"a.b.c": "p"}}}
    resolver = _make_resolver({"a.b.c": "deep-value"})
    result = resolve_dict_secrets(data, resolver)
    assert result["a"]["b"]["c"] == "deep-value"
