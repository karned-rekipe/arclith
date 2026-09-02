import json
import logging

import httpx
import pytest

from arclith.adapters.outbound.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)
from arclith.domain.ports.outbound.embedding import (
    EmbeddingAuthenticationError,
    EmbeddingDimensionMismatch,
    EmbeddingInvalidInput,
    EmbeddingRateLimitError,
    EmbeddingText,
    EmbeddingUnavailable,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings


def _settings(**updates: object) -> EmbeddingSettings:
    values: dict[str, object] = {
        "adapter": "openai-compatible",
        "base_url": "http://embedding.local/v1",
        "api_key": "local-dev",
        "model_name": "local-embedding-model",
        "dimensions": 2,
        "batch_size": 2,
        "timeout": 5.0,
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


@pytest.mark.asyncio
async def test_openai_compatible_request_and_provider_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response_for(request, reverse=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await OpenAICompatibleEmbeddingAdapter(
            _settings(), client=client
        ).embed_texts(
            [
                EmbeddingText(id="first", text="alpha"),
                EmbeddingText(id="second", text="beta"),
            ]
        )

    request = requests[0]
    assert str(request.url) == "http://embedding.local/v1/embeddings"
    assert request.headers["authorization"] == "Bearer local-dev"
    assert json.loads(request.content) == {
        "input": ["alpha", "beta"],
        "model": "local-embedding-model",
        "dimensions": 2,
    }
    assert [result.id for result in response.results] == ["first", "second"]
    assert [result.index for result in response.results] == [0, 1]
    assert [result.vector for result in response.results] == [
        [1.0, 2.0],
        [2.0, 3.0],
    ]
    assert response.usage is not None
    assert response.usage.total_tokens == 2


@pytest.mark.asyncio
async def test_openai_compatible_splits_batches_and_aggregates_usage() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch_sizes.append(len(json.loads(request.content)["input"]))
        return _response_for(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await OpenAICompatibleEmbeddingAdapter(
            _settings(batch_size=2), client=client
        ).embed_texts(
            [EmbeddingText(id=str(index), text=f"text-{index}") for index in range(5)]
        )

    assert batch_sizes == [2, 2, 1]
    assert [result.index for result in response.results] == list(range(5))
    assert [result.id for result in response.results] == [
        str(index) for index in range(5)
    ]
    assert response.usage is not None
    assert response.usage.prompt_tokens == 5
    assert response.usage.total_tokens == 5


@pytest.mark.asyncio
async def test_openai_compatible_rejects_dimension_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "local-embedding-model",
                "data": [{"index": 0, "embedding": [1.0]}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingDimensionMismatch, match="dimensions"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_openai_compatible_maps_authentication_errors(
    status_code: int,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, json={"error": "denied"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingAuthenticationError, match="authentication"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_compatible_maps_rate_limit() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, json={"error": "slow down"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingRateLimitError, match="rate limit"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_compatible_maps_invalid_provider_request() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(422, json={"error": "invalid"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingInvalidInput, match="rejected"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_openai_compatible_maps_transport_failures(
    error_type: type[httpx.TransportError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("provider unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(_settings(), client=client)
        with pytest.raises(EmbeddingUnavailable, match="unavailable"):
            await adapter.embed_texts([EmbeddingText(text="alpha")])


@pytest.mark.asyncio
async def test_openai_compatible_does_not_log_key_or_raw_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "secret-provider-key"
    raw_text = "private raw text"
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(500, json={"error": raw_text})
    )

    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleEmbeddingAdapter(
            _settings(api_key=secret), client=client
        )
        with pytest.raises(EmbeddingUnavailable) as error:
            await adapter.embed_texts([EmbeddingText(text=raw_text)])

    captured = caplog.text + str(error.value)
    assert secret not in captured
    assert raw_text not in captured
