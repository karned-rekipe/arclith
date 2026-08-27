from __future__ import annotations

import pytest

from arclith.adapters.outbound.langsmith.config import resolve_langsmith_config
from arclith.infrastructure.config import LangSmithSettings


def test_resolve_langsmith_config_applies_environment_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret-key")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "workspace-env")
    monkeypatch.setenv("LANGSMITH_PROJECT", "project-env")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_TRACING_MODE", "hybrid")
    monkeypatch.setenv("LANGSMITH_TRACING_SAMPLING_RATE", "0.25")
    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "false")
    monkeypatch.setenv("LANGSMITH_HIDE_OUTPUTS", "true")
    monkeypatch.setenv("LANGSMITH_HIDE_METADATA", "false")
    settings = LangSmithSettings.model_validate(
        {
            "project": "yaml-project",
            "endpoint": "https://yaml.example.test",
            "tracing": {"enabled": True, "mode": "langsmith", "sampling_rate": 1.0},
            "capture": {"inputs": False, "outputs": True, "metadata": False},
        }
    )

    resolved = resolve_langsmith_config(settings)

    assert resolved.project == "project-env"
    assert resolved.endpoint == "https://eu.api.smith.langchain.com"
    assert resolved.workspace_id == "workspace-env"
    assert resolved.tracing_enabled is False
    assert resolved.tracing_mode == "hybrid"
    assert resolved.sampling_rate == 0.25
    assert resolved.capture_inputs is True
    assert resolved.capture_outputs is False
    assert resolved.capture_metadata is True
    assert "secret-key" not in repr(resolved)


def test_resolve_langsmith_config_uses_custom_secret_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_LANGSMITH_KEY", "custom-secret")
    monkeypatch.setenv("CUSTOM_WORKSPACE", "custom-workspace")
    settings = LangSmithSettings(
        project="agent-tests",
        api_key_env="CUSTOM_LANGSMITH_KEY",
        workspace_id_env="CUSTOM_WORKSPACE",
        tracing={"mode": "langsmith"},
    )

    resolved = resolve_langsmith_config(settings)

    assert resolved.api_key == "custom-secret"
    assert resolved.workspace_id == "custom-workspace"
    assert resolved.tracing_mode == "langsmith"


def test_resolve_langsmith_config_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="aucune cle API"):
        resolve_langsmith_config(LangSmithSettings(project="agent-tests"))


def test_resolve_langsmith_config_names_custom_missing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_LANGSMITH_KEY", raising=False)

    with pytest.raises(RuntimeError, match="CUSTOM_LANGSMITH_KEY"):
        resolve_langsmith_config(
            LangSmithSettings(
                project="agent-tests",
                api_key_env="CUSTOM_LANGSMITH_KEY",
            )
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("LANGSMITH_TRACING", "sometimes", "booleen"),
        ("LANGSMITH_TRACING_SAMPLING_RATE", "many", "nombre"),
        ("LANGSMITH_TRACING_SAMPLING_RATE", "1.5", "0.0 et 1.0"),
        ("LANGSMITH_TRACING_MODE", "magic", "Valeurs"),
    ],
)
def test_resolve_langsmith_config_rejects_invalid_overrides(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=message):
        resolve_langsmith_config(LangSmithSettings(project="agent-tests"))
