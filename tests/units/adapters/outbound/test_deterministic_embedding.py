import math

import pytest

from arclith.adapters.outbound.deterministic import DeterministicEmbeddingAdapter
from arclith.domain.ports.outbound.embedding import (
    EmbeddingInvalidInput,
    EmbeddingText,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings


def _adapter(*, dimensions: int = 8, batch_size: int = 2, normalize: bool = True):
    return DeterministicEmbeddingAdapter(
        EmbeddingSettings(
            adapter="deterministic",
            model_name="deterministic-test",
            dimensions=dimensions,
            batch_size=batch_size,
            normalize=normalize,
        )
    )


@pytest.mark.asyncio
async def test_deterministic_embedding_is_stable_across_instances() -> None:
    inputs = [EmbeddingText(id="doc-1", text="stable text")]

    first = await _adapter().embed_texts(inputs)
    second = await _adapter().embed_texts(inputs)

    assert first == second
    assert first.results[0].id == "doc-1"
    assert len(first.results[0].vector) == 8


@pytest.mark.asyncio
async def test_deterministic_embedding_preserves_order_across_sub_batches() -> None:
    inputs = [
        EmbeddingText(id=f"doc-{index}", text=f"text {index}") for index in range(5)
    ]

    response = await _adapter(batch_size=2).embed_texts(inputs)

    assert [result.index for result in response.results] == list(range(5))
    assert [result.id for result in response.results] == [
        f"doc-{index}" for index in range(5)
    ]


@pytest.mark.asyncio
async def test_deterministic_embedding_normalizes_vectors_when_enabled() -> None:
    response = await _adapter(dimensions=16).embed_texts(
        [EmbeddingText(text="normalized")]
    )

    norm = math.sqrt(sum(value * value for value in response.results[0].vector))
    assert norm == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_deterministic_embedding_rejects_empty_batch() -> None:
    with pytest.raises(EmbeddingInvalidInput, match="inputs must not be empty"):
        await _adapter().embed_texts([])
