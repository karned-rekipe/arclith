import pytest
from pydantic import ValidationError

from arclith.domain.ports.outbound.embedding import (
    EmbeddingInvalidInput,
    EmbeddingResponse,
    EmbeddingResult,
    EmbeddingText,
    validate_embedding_inputs,
)


def _result(
    index: int,
    *,
    dimensions: int = 2,
    model_name: str = "test-model",
) -> EmbeddingResult:
    return EmbeddingResult(
        index=index,
        vector=[0.25] * dimensions,
        model_name=model_name,
        dimensions=dimensions,
    )


def test_embedding_text_trims_and_rejects_empty_content() -> None:
    assert EmbeddingText(text="  hello  ").text == "hello"

    with pytest.raises(ValidationError, match="must not be empty"):
        EmbeddingText(text=" \n\t ")


def test_validate_embedding_inputs_rejects_empty_batch() -> None:
    with pytest.raises(EmbeddingInvalidInput, match="inputs must not be empty"):
        validate_embedding_inputs([])


def test_embedding_result_rejects_vector_dimension_mismatch() -> None:
    with pytest.raises(ValidationError, match="vector length"):
        EmbeddingResult(
            index=0,
            vector=[0.25],
            model_name="test-model",
            dimensions=2,
        )


def test_embedding_response_accepts_ordered_consistent_results() -> None:
    response = EmbeddingResponse(
        results=[_result(0), _result(1)],
        model_name="test-model",
        dimensions=2,
    )

    assert [result.index for result in response.results] == [0, 1]
    assert response.dimensions == 2


@pytest.mark.parametrize(
    ("results", "message"),
    [
        ([_result(1), _result(0)], "preserve input order"),
        ([_result(0, dimensions=3)], "response dimensions"),
        ([_result(0, model_name="other-model")], "response model_name"),
    ],
)
def test_embedding_response_rejects_inconsistent_results(
    results: list[EmbeddingResult], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        EmbeddingResponse(
            results=results,
            model_name="test-model",
            dimensions=2,
        )
