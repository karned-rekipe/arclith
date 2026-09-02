import json
import logging

import httpx
import pytest

from arclith.adapters.outbound.openai import OpenAIEmbeddingAdapter
from arclith.domain.ports.outbound.embedding import (
    EmbeddingAuthenticationError,
    EmbeddingDimensionMismatch,
    EmbeddingRateLimitError,
    EmbeddingText,
    EmbeddingUnavailable,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings


def _settings(**updates: object) -> EmbeddingSettings:
    values: dict[str, object] = {
        "adapter": "openai",
        "api_key": "test-key",
        "model_name": "configured-embedding-model",
        "dimensions": 2,
        "batch_size": 2,
        "timeout": 5.0,
        "encoding_format": "float",
        "normalize": False,
    }
    values.update(updates)
    return EmbeddingSettings.model_validate(values)


def _response_for(request: httpx.Request, *, reverse: bool = False) -> httpx.Response:
    payload = json.loads(request.content)
    indices = list(range(len(payload["input"])))
    if reverse:
        indices.reverse()
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": payload["model"],
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [float(index + 1), float(index + 2)],
                }
                for index in indices
            ],
            "usage": {"prompt_tokens": len(indices), "total_tokens": len(indices)},
        },
    )


def test_openai_embedding_requires_api_key_before_any_request() -> None:
    with pytest.raises(EmbeddingAuthenticationError, match="OPENAI_API_KEY"):
        OpenAIEmbeddingAdapter(_settings(api_key=None))


@pytest.mark.asyncio
async def test_openai_embedding_sends_official_request_and_preserves_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response_for(request, reverse=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await OpenAIEmbeddingAdapter(_settings(), client=client).embed_texts(
            [
                EmbeddingText(id="first", text="alpha"),
                EmbeddingText(id="second", text="beta"),
            ]
        )

    request = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/embeddings"
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "input": ["alpha", "beta"],
        "model": "configured-embedding-model",
        "dimensions": 2,
        "encoding_format": "float",
    }
    assert [result.id for result in response.results] == ["first", "second"]
    assert [result.index for result in response.results] == [0, 1]
    assert response.dimensions == 2
    assert response.usage is not None
    assert response.usage.prompt_tokens == 2
    assert response.usage.total_tokens == 2


@pytest.mark.asyncio
async def test_openai_embedding_omits_dimensions_and_infers_response_size() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "configured-embedding-model",
                "data": [{"index": 0, "embedding": [1.0, 2.0, 3.0]}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await OpenAIEmbeddingAdapter(
            _settings(dimensions=None), client=client
        ).embed_texts([EmbeddingText(text="alpha")])

    payload = json.loads(requests[0].content)
    assert "dimensions" not in payload
    assert payload["encoding_format"] == "float"
    assert response.dimensions == 3
    assert response.results[0].dimensions == 3


@pytest.mark.asyncio
async def test_openai_embedding_rejects_configured_dimension_mismatch() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "model": "configured-embedding-model",
                "data": [{"index": 0, "embedding": [1.0]}],
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAIEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingDimensionMismatch, match="dimensions"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_embedding_rejects_inconsistent_inferred_batch_dimensions() -> (
    None
):
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        dimensions = 2 if request_count == 1 else 3
        return httpx.Response(
            200,
            json={
                "model": "configured-embedding-model",
                "data": [{"index": 0, "embedding": [1.0] * dimensions}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIEmbeddingAdapter(
            _settings(dimensions=None, batch_size=1), client=client
        )
        with pytest.raises(EmbeddingDimensionMismatch, match="inconsistent"):
            await adapter.embed_texts(
                [EmbeddingText(text="alpha"), EmbeddingText(text="beta")]
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_openai_embedding_maps_authentication_errors(status_code: int) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, json={"error": "denied"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAIEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingAuthenticationError, match="authentication"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_embedding_maps_rate_limit_or_quota() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, json={"error": "quota"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAIEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingRateLimitError, match="rate limit or quota"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_embedding_maps_timeout_without_sensitive_details() -> None:
    secret = "private-provider-key"
    raw_text = "private raw text"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(raw_text, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIEmbeddingAdapter(_settings(api_key=secret), client=client)
        with pytest.raises(EmbeddingUnavailable) as error:
            await adapter.embed_texts([EmbeddingText(text=raw_text)])

    message = str(error.value)
    assert secret not in message
    assert raw_text not in message


@pytest.mark.asyncio
async def test_openai_embedding_does_not_log_secret_or_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-provider-key"
    raw_text = "private raw text"
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(500, json={"error": raw_text})
    )

    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAIEmbeddingAdapter(_settings(api_key=secret), client=client)
        with pytest.raises(EmbeddingUnavailable) as error:
            await adapter.embed_texts([EmbeddingText(text=raw_text)])

    captured = caplog.text + str(error.value)
    assert secret not in captured
    assert raw_text not in captured
