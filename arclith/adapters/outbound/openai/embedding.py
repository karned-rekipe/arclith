from __future__ import annotations

from arclith.adapters.outbound.openai_compatible.embedding import (
    OpenAICompatibleEmbeddingAdapter,
)


class OpenAIEmbeddingAdapter(OpenAICompatibleEmbeddingAdapter):
    """Official OpenAI embeddings API adapter with mandatory credentials."""

    _include_encoding_format = True
    _requires_api_key = True
    _missing_api_key_message = (
        "OpenAI embeddings require adapters.embedding.api_key; "
        "map OPENAI_API_KEY through config/secrets.yaml, environment, or Vault"
    )
    _rate_limit_message = "OpenAI embedding rate limit or quota exceeded"
