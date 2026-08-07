from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from arclith.adapters.outbound.chain.secret_adapter import ChainSecretAdapter
from arclith.adapters.outbound.env.secret_adapter import EnvSecretAdapter
from arclith.adapters.outbound.vault.secret_adapter import VaultSecretAdapter
from arclith.adapters.outbound.yaml.secret_adapter import YamlSecretAdapter


# ── YamlSecretAdapter ─────────────────────────────────────────────────────────

def test_yaml_reads_nested_value(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text(
        yaml.dump({"adapters": {"mongodb": {"uri": "mongodb://localhost:5971"}}})
    )
    adapter = YamlSecretAdapter(tmp_path / "s.yaml")
    assert adapter.get("adapters.mongodb.uri", "ignored") == "mongodb://localhost:5971"


def test_yaml_reads_top_level_key(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text(yaml.dump({"key": "value"}))
    adapter = YamlSecretAdapter(tmp_path / "s.yaml")
    assert adapter.get("key", "ignored") == "value"


def test_yaml_missing_key_returns_none(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text(yaml.dump({"adapters": {}}))
    adapter = YamlSecretAdapter(tmp_path / "s.yaml")
    assert adapter.get("adapters.mongodb.uri", "ignored") is None


def test_yaml_missing_file_returns_none(tmp_path: Path) -> None:
    adapter = YamlSecretAdapter(tmp_path / "nonexistent.yaml")
    assert adapter.get("adapters.mongodb.uri", "ignored") is None


def test_yaml_caches_data(tmp_path: Path) -> None:
    f = tmp_path / "s.yaml"
    f.write_text(yaml.dump({"key": "original"}))
    adapter = YamlSecretAdapter(f)
    adapter.get("key", "ignored")          # first call — loads file
    f.write_text(yaml.dump({"key": "changed"}))
    assert adapter.get("key", "ignored") == "original"  # still cached


def test_yaml_intermediate_key_not_dict_returns_none(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text(yaml.dump({"adapters": "not-a-dict"}))
    adapter = YamlSecretAdapter(tmp_path / "s.yaml")
    assert adapter.get("adapters.mongodb.uri", "ignored") is None


# ── EnvSecretAdapter ──────────────────────────────────────────────────────────

def test_env_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTERS_MONGODB_URI", "mongodb://env:5971")
    assert EnvSecretAdapter().get("adapters.mongodb.uri", "ignored") == "mongodb://env:5971"


def test_env_missing_var_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADAPTERS_MONGODB_URI", raising=False)
    assert EnvSecretAdapter().get("adapters.mongodb.uri", "ignored") is None


def test_env_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LM_INTENT_INTERPRETER_API_KEY", "sk-test")
    assert EnvSecretAdapter().get("lm.intent_interpreter.api_key", "ignored") == "sk-test"


def test_env_uses_explicit_secret_key_before_derived_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ADAPTERS_LM_API_KEY", "sk-derived")

    assert EnvSecretAdapter().get("adapters.lm.api_key", "OPENAI_API_KEY") == "sk-openai"


def test_env_empty_string_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTERS_MONGODB_URI", "")
    assert EnvSecretAdapter().get("adapters.mongodb.uri", "ignored") is None


# ── ChainSecretAdapter ────────────────────────────────────────────────────────

def test_chain_returns_first_non_none() -> None:
    a1, a2 = MagicMock(), MagicMock()
    a1.get.return_value = None
    a2.get.return_value = "found"
    chain = ChainSecretAdapter([a1, a2])
    assert chain.get("p", "k") == "found"
    a1.get.assert_called_once_with("p", "k")
    a2.get.assert_called_once_with("p", "k")


def test_chain_stops_at_first_hit() -> None:
    a1, a2 = MagicMock(), MagicMock()
    a1.get.return_value = "first"
    chain = ChainSecretAdapter([a1, a2])
    assert chain.get("p", "k") == "first"
    a2.get.assert_not_called()


def test_chain_returns_none_when_all_fail() -> None:
    a1 = MagicMock()
    a1.get.return_value = None
    chain = ChainSecretAdapter([a1])
    assert chain.get("p", "k") is None


def test_chain_empty_adapters_returns_none() -> None:
    assert ChainSecretAdapter([]).get("p", "k") is None


# ── VaultSecretAdapter ────────────────────────────────────────────────────────

def test_vault_returns_none_if_hvac_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "tok")
    adapter = VaultSecretAdapter(addr="http://127.0.0.1:8200")
    with patch.dict("sys.modules", {"hvac": None}):
        assert adapter.get("adapters.mongodb.uri", "rekipe/sample/mongodb") is None


def test_vault_returns_none_if_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with patch("pathlib.Path.home", return_value=tmp_path):  # no .vault-token file
        adapter = VaultSecretAdapter(addr="http://127.0.0.1:8200")
        assert adapter.get("adapters.mongodb.uri", "rekipe/sample/mongodb") is None


def test_vault_reads_token_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    (tmp_path / ".vault-token").write_text("file-token")

    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "mongodb://vault:5971"}}
    }
    mock_hvac = MagicMock()
    mock_hvac.Client.return_value = mock_client

    with patch("pathlib.Path.home", return_value=tmp_path), \
            patch.dict("sys.modules", {"hvac": mock_hvac}):
        result = VaultSecretAdapter(addr="http://127.0.0.1:8200").get(
            "adapters.mongodb.uri", "rekipe/sample/mongodb"
        )
    assert result == "mongodb://vault:5971"
    mock_hvac.Client.assert_called_with(url="http://127.0.0.1:8200", token="file-token")


def test_vault_returns_none_if_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "bad-token")
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = False
    mock_hvac = MagicMock()
    mock_hvac.Client.return_value = mock_client
    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        assert VaultSecretAdapter(addr="http://127.0.0.1:8200").get("p", "k") is None


def test_vault_returns_none_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "tok")
    mock_client = MagicMock()
    mock_client.is_authenticated.side_effect = Exception("connection refused")
    mock_hvac = MagicMock()
    mock_hvac.Client.return_value = mock_client
    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        assert VaultSecretAdapter(addr="http://127.0.0.1:8200").get("p", "k") is None


def test_vault_returns_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "root-token")
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "mongodb://vault:5971"}}
    }
    mock_hvac = MagicMock()
    mock_hvac.Client.return_value = mock_client
    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        result = VaultSecretAdapter(addr="http://127.0.0.1:8200", mount="kv").get(
            "adapters.mongodb.uri", "rekipe/sample/mongodb"
        )
    assert result == "mongodb://vault:5971"
    mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
        path="rekipe/sample/mongodb",
        mount_point="kv",
        raise_on_deleted_version=True,
    )


def test_vault_returns_none_if_value_field_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "tok")
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {}}  # no "value" key
    }
    mock_hvac = MagicMock()
    mock_hvac.Client.return_value = mock_client
    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        assert VaultSecretAdapter(addr="http://127.0.0.1:8200").get("p", "k") is None
