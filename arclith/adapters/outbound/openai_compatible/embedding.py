from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from arclith.domain.ports.outbound.embedding import (
    EmbeddingAuthenticationError,
    EmbeddingDimensionMismatch,
    EmbeddingError,
    EmbeddingInvalidInput,
    EmbeddingPort,
    EmbeddingRateLimitError,
    EmbeddingResponse,
    EmbeddingResult,
    EmbeddingText,
    EmbeddingUnavailable,
    EmbeddingUsage,
    validate_embedding_inputs,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings

if TYPE_CHECKING:
    import httpx


class OpenAICompatibleEmbeddingAdapter(EmbeddingPort):
    """Text embeddings over the OpenAI-compatible HTTP protocol."""

    def __init__(
        self,
        settings: EmbeddingSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.base_url is None:
            raise ValueError("OpenAI-compatible embedding base_url is required")
        self._settings = settings
        self._client = client

    async def embed_texts(self, inputs: Sequence[EmbeddingText]) -> EmbeddingResponse:
        validated = validate_embedding_inputs(inputs)
        if self._client is not None:
            return await self._embed_with_client(self._client, validated)

        httpx = _require_httpx()
        async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
            return await self._embed_with_client(client, validated)

    async def _embed_with_client(
        self,
        client: httpx.AsyncClient,
        inputs: tuple[EmbeddingText, ...],
    ) -> EmbeddingResponse:
        results: list[EmbeddingResult] = []
        prompt_tokens = 0
        total_tokens = 0
        has_prompt_tokens = False
        has_total_tokens = False

        for offset in range(0, len(inputs), self._settings.batch_size):
            batch = inputs[offset : offset + self._settings.batch_size]
            batch_results, batch_usage = await self._request_batch(
                client,
                batch,
                offset=offset,
            )
            results.extend(batch_results)
            if batch_usage is not None and batch_usage.prompt_tokens is not None:
                prompt_tokens += batch_usage.prompt_tokens
                has_prompt_tokens = True
            if batch_usage is not None and batch_usage.total_tokens is not None:
                total_tokens += batch_usage.total_tokens
                has_total_tokens = True

        usage = None
        if has_prompt_tokens or has_total_tokens:
            usage = EmbeddingUsage(
                prompt_tokens=prompt_tokens if has_prompt_tokens else None,
                total_tokens=total_tokens if has_total_tokens else None,
            )
        return EmbeddingResponse(
            results=results,
            model_name=self._settings.model_name,
            dimensions=self._settings.dimensions,
            usage=usage,
        )

    async def _request_batch(
        self,
        client: httpx.AsyncClient,
        inputs: tuple[EmbeddingText, ...],
        *,
        offset: int,
    ) -> tuple[list[EmbeddingResult], EmbeddingUsage | None]:
        httpx = _require_httpx()
        payload: dict[str, object] = {
            "input": [item.text for item in inputs],
            "model": self._settings.model_name,
            "dimensions": self._settings.dimensions,
        }
        try:
            response = await client.post(
                f"{self._settings.base_url}/embeddings",
                json=payload,
                headers=self._request_headers(),
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise EmbeddingUnavailable("embedding provider is unavailable") from error

        _raise_for_status(response.status_code)
        try:
            body = response.json()
        except (TypeError, ValueError) as error:
            raise EmbeddingError(
                "embedding provider returned an invalid JSON response"
            ) from error
        return self._parse_response(body, inputs, offset=offset)

    def _parse_response(
        self,
        body: Any,
        inputs: tuple[EmbeddingText, ...],
        *,
        offset: int,
    ) -> tuple[list[EmbeddingResult], EmbeddingUsage | None]:
        response = _response_mapping(body)
        _validate_provider_model(response.get("model"), self._settings.model_name)
        data = _response_data(response.get("data"), expected_count=len(inputs))

        by_index: dict[int, list[float]] = {}
        for item in data:
            index, vector = self._parse_result_item(item)
            if index in by_index or index >= len(inputs):
                raise EmbeddingError(
                    "embedding provider returned invalid result indices"
                )
            by_index[index] = vector
        if set(by_index) != set(range(len(inputs))):
            raise EmbeddingError("embedding provider returned invalid result indices")

        results = [
            EmbeddingResult(
                id=inputs[index].id,
                index=offset + index,
                vector=by_index[index],
                model_name=self._settings.model_name,
                dimensions=self._settings.dimensions,
            )
            for index in range(len(inputs))
        ]
        return results, _parse_usage(response.get("usage"))

    def _parse_result_item(self, item: Any) -> tuple[int, list[float]]:
        result = _result_mapping(item)
        index = _provider_index(result.get("index"))
        parsed = _provider_vector(
            result.get("embedding"),
            dimensions=self._settings.dimensions,
        )
        if self._settings.normalize:
            parsed = _normalize_vector(parsed)
        return index, parsed

    def _request_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._settings.api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        return headers


def _parse_usage(value: Any) -> EmbeddingUsage | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EmbeddingError("embedding provider returned invalid usage metadata")
    return EmbeddingUsage(
        prompt_tokens=_usage_value(value, "prompt_tokens"),
        total_tokens=_usage_value(value, "total_tokens"),
    )


def _response_mapping(value: Any) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise EmbeddingError("embedding provider returned an invalid response")
    return value


def _validate_provider_model(value: Any, expected: str) -> None:
    if value is not None and value != expected:
        raise EmbeddingError("embedding provider returned an unexpected model")


def _response_data(value: Any, *, expected_count: int) -> list[Any]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise EmbeddingError("embedding provider returned an invalid result count")
    return value


def _result_mapping(value: Any) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise EmbeddingError("embedding provider returned an invalid result")
    return value


def _provider_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EmbeddingError("embedding provider returned an invalid result index")
    return value


def _provider_vector(value: Any, *, dimensions: int) -> list[float]:
    if not isinstance(value, list) or any(
        not _is_finite_number(component) for component in value
    ):
        raise EmbeddingError("embedding provider returned an invalid vector")
    if len(value) != dimensions:
        raise EmbeddingDimensionMismatch(
            "embedding provider vector dimensions do not match configuration"
        )
    return [float(component) for component in value]


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
    )


def _usage_value(usage: Mapping[Any, Any], name: str) -> int | None:
    value = usage.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EmbeddingError("embedding provider returned invalid usage metadata")
    return value


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise EmbeddingError("embedding provider returned a zero vector")
    return [value / norm for value in vector]


def _raise_for_status(status_code: int) -> None:
    if status_code < 400:
        return
    if status_code in {401, 403}:
        raise EmbeddingAuthenticationError("embedding provider rejected authentication")
    if status_code == 429:
        raise EmbeddingRateLimitError("embedding provider rate limit exceeded")
    if 400 <= status_code < 500:
        raise EmbeddingInvalidInput("embedding provider rejected the request")
    raise EmbeddingUnavailable("embedding provider is unavailable")


def _require_httpx() -> Any:
    try:
        import httpx
    except ImportError as error:  # pragma: no cover - exercised in isolated installs
        raise RuntimeError(
            "OpenAI-compatible embeddings require arclith[embedding]"
        ) from error
    return httpx
