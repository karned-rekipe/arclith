import pytest

from arclith.infrastructure.config import LMSettings
from arclith.infrastructure.lm import build_pydantic_ai_model


# ── LMSettings defaults ───────────────────────────────────────────────────────

def test_lm_settings_defaults():
    s = LMSettings()
    assert s.provider == "anthropic"
    assert s.model_name == "claude-sonnet-4-5"
    assert s.api_key == ""
    assert s.base_url is None


def test_lm_settings_openai():
    s = LMSettings(provider="openai", model_name="gpt-4o", api_key="sk-x", base_url="http://localhost:11434/v1")
    assert s.provider == "openai"
    assert s.base_url == "http://localhost:11434/v1"


def test_lm_settings_invalid_provider():
    with pytest.raises(Exception):
        LMSettings(provider="mistral")  # type: ignore[arg-type]


# ── build_pydantic_ai_model ───────────────────────────────────────────────────

def test_build_anthropic_model():
    settings = LMSettings(provider="anthropic", model_name="claude-sonnet-4-5", api_key="sk-ant-test")
    model = build_pydantic_ai_model(settings)
    from pydantic_ai.models.anthropic import AnthropicModel
    assert isinstance(model, AnthropicModel)
    assert model.profile["default_structured_output_mode"] == "native"


def test_build_openai_model():
    settings = LMSettings(
        provider="openai",
        model_name="llama3",
        api_key="ollama",
        base_url="http://localhost:11434/v1",
    )
    model = build_pydantic_ai_model(settings)
    from pydantic_ai.models.openai import OpenAIChatModel
    assert isinstance(model, OpenAIChatModel)
    assert model.profile["default_structured_output_mode"] == "native"
    assert model.profile["supports_json_schema_output"] is True
    assert model.profile["supports_json_object_output"] is False


def test_build_openai_model_requires_base_url():
    settings = LMSettings(provider="openai", model_name="gpt-4o", api_key="sk-x")
    with pytest.raises(ValueError, match="base_url is required"):
        build_pydantic_ai_model(settings)
