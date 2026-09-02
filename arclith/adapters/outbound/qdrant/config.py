from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from arclith.adapters.context import get_adapter_tenant_context
from arclith.domain.ports.outbound.vector_store import VectorStoreUnavailable
from arclith.infrastructure.settings.vector_store import VectorStoreSettings


@dataclass(frozen=True)
class ResolvedQdrantConfig:
    url: str
    api_key: str | None
    collection_name: str
    vector_size: int
    distance: str
    prefer_grpc: bool
    timeout: float
    create_collection: bool


def resolve_qdrant_config(settings: VectorStoreSettings) -> ResolvedQdrantConfig:
    url = settings.url
    api_key = settings.api_key
    collection_name: str | None = settings.collection_name
    if settings.multitenant:
        coords = get_adapter_tenant_context("qdrant")
        if coords is not None:
            url = _tenant_value(coords.get("url"), url)
            api_key = _tenant_value(coords.get("api_key"), api_key)
            collection_name = _tenant_value(
                coords.get("collection_name"), collection_name
            )

    return ResolvedQdrantConfig(
        url=_validated_url(url),
        api_key=_optional_text(api_key),
        collection_name=_validated_collection_name(collection_name),
        vector_size=settings.vector_size,
        distance=settings.distance,
        prefer_grpc=settings.prefer_grpc,
        timeout=settings.timeout,
        create_collection=settings.create_collection,
    )


def _tenant_value(value: str | None, fallback: str | None) -> str | None:
    return _optional_text(value) or fallback


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validated_url(value: str | None) -> str:
    normalized = (_optional_text(value) or "").rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise VectorStoreUnavailable(
            "qdrant vector-store requires a credential-free HTTP URL"
        )
    return normalized


def _validated_collection_name(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise VectorStoreUnavailable("qdrant vector-store requires a collection name")
    return normalized
