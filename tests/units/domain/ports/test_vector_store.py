import math

import pytest
from pydantic import ValidationError

from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchHit,
    VectorSearchQuery,
)


def test_vector_point_accepts_nested_json_payload() -> None:
    point = VectorPoint(
        id="  doc-1  ",
        vector=[0.25, -0.5],
        payload={
            "published": True,
            "rank": 3,
            "tags": ["python", None],
            "metadata": {"language": "fr"},
        },
    )

    assert point.id == "doc-1"
    assert point.payload["metadata"] == {"language": "fr"}


@pytest.mark.parametrize("invalid", [object(), math.nan, math.inf])
def test_vector_point_rejects_non_json_or_non_finite_payload(invalid: object) -> None:
    with pytest.raises(ValidationError, match="payload"):
        VectorPoint(id="doc-1", vector=[1.0], payload={"value": invalid})


def test_vector_search_query_rejects_non_finite_filter() -> None:
    with pytest.raises(ValidationError, match="filters"):
        VectorSearchQuery(vector=[1.0], filters={"nested": [math.nan]})


@pytest.mark.parametrize("invalid", [[], [math.nan], [math.inf]])
def test_vector_models_reject_empty_or_non_finite_vectors(invalid: list[float]) -> None:
    with pytest.raises(ValidationError, match="vector"):
        VectorPoint(id="doc-1", vector=invalid)


def test_vector_search_query_requires_positive_limit_and_finite_threshold() -> None:
    with pytest.raises(ValidationError, match="limit"):
        VectorSearchQuery(vector=[1.0], limit=0)

    with pytest.raises(ValidationError, match="score_threshold"):
        VectorSearchQuery(vector=[1.0], score_threshold=math.inf)


def test_vector_search_hit_rejects_non_finite_score() -> None:
    with pytest.raises(ValidationError, match="score"):
        VectorSearchHit(id="doc-1", score=math.nan)
