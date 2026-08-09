from __future__ import annotations

from arclith.infrastructure.config import LMSettings


def build_pydantic_ai_model(settings: LMSettings):
    """Factory qui retourne un modèle PydanticAI à partir de LMSettings.

    Les imports pydantic_ai sont lazy pour ne pas casser les projets
    qui n'installent pas l'extra [langgraph].
    """
    if settings.provider == "anthropic":
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.profiles.anthropic import AnthropicModelProfile
            from pydantic_ai.providers.anthropic import AnthropicProvider
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Le provider LLM 'anthropic' requiert l'extra optionnel "
                "`arclith[langgraph]` avec le support pydantic-ai Anthropic."
            ) from exc

        return AnthropicModel(
            settings.model_name,
            provider=AnthropicProvider(api_key=settings.api_key),
            profile=AnthropicModelProfile(default_structured_output_mode="native"),
        )

    # provider == "openai" — aussi utilisé pour LLMs locaux (Ollama, LM Studio…)
    if not settings.base_url:
        raise ValueError("base_url is required for provider='openai'")

    try:
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIModelProfile
        from pydantic_ai.providers.openai import OpenAIProvider
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Le provider LLM 'openai' requiert l'extra optionnel "
            "`arclith[langgraph]` avec le support pydantic-ai OpenAI."
        ) from exc

    return OpenAIChatModel(
        settings.model_name,
        provider=OpenAIProvider(base_url=settings.base_url, api_key=settings.api_key),
        profile=OpenAIModelProfile(
            default_structured_output_mode="native",
            supports_json_schema_output=True,
            supports_json_object_output=False,
            openai_chat_send_back_thinking_parts=False,
        ),
    )
