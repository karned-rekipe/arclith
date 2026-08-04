from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field
from uuid6 import uuid7

T = TypeVar("T")


class ResponseMetadata(BaseModel):
    """Métadonnées de réponse API (niveau 3 Richardson - liens HATEOAS optionnels)."""

    request_id: str = Field(
        default_factory=lambda: str(uuid7()),
        description = "Identifiant unique de la requête pour le traçage (UUIDv7 time-ordered). Peut être fourni par le client via header X-Request-ID.",
        examples=["01951234-5678-7abc-def0-123456789abc"],
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Horodatage de la réponse (UTC).",
        examples=["2026-03-25T10:30:00+00:00"],
    )
    version: str = Field(
        default="v1",
        description="Version de l'API.",
        examples=["v1", "v2"],
    )
    duration_ms: int | None = Field(
        default=None,
        description="Durée de traitement en millisecondes.",
        examples=[45, 120, None],
    )
    links: dict[str, str] | None = Field(
        default=None,
        description="Liens HATEOAS pour la découvrabilité (optionnel).",
        examples=[
            {
                "self": "/v1/ingredients/01951234-5678-7abc",
                "collection": "/v1/ingredients",
                "duplicate": "/v1/ingredients/01951234-5678-7abc/duplicate",
            }
        ],
    )


class ErrorDetail(BaseModel):
    """Détails d'une erreur API."""

    type: str = Field(
        description="Type d'erreur.",
        examples=["validation_error", "not_found", "server_error", "conflict"],
    )
    message: str = Field(
        description="Message d'erreur lisible.",
        examples=["Ingredient not found", "Name cannot be empty"],
    )
    field: str | None = Field(
        default=None,
        description="Champ concerné par l'erreur (si applicable).",
        examples=["name", "unit", None],
    )


class ApiResponse(BaseModel, Generic[T]):
    """Wrapper générique pour toutes les réponses API."""

    status: str = Field(
        description="Statut de la réponse : 'success' ou 'error'.",
        examples=["success", "error"],
    )
    data: T | None = Field(
        default=None,
        description="Payload de la réponse (None si status='error').",
    )
    error: ErrorDetail | None = Field(
        default=None,
        description="Détails d'erreur (None si status='success').",
    )
    metadata: ResponseMetadata = Field(
        default_factory=ResponseMetadata,
        description="Métadonnées de la réponse.",
    )


class PaginationInfo(BaseModel):
    """Informations de pagination."""

    total: int = Field(
        description="Nombre total d'éléments.",
        examples=[42, 100],
    )
    page: int = Field(
        default=1,
        description="Numéro de page actuelle (commence à 1).",
        examples=[1, 2, 5],
    )
    per_page: int = Field(
        default=20,
        description="Nombre d'éléments par page.",
        examples=[10, 20, 50],
    )
    pages: int = Field(
        description="Nombre total de pages.",
        examples=[5, 10],
    )
    has_next: bool = Field(
        description="True s'il existe une page suivante.",
        examples=[True, False],
    )
    has_prev: bool = Field(
        description="True s'il existe une page précédente.",
        examples=[True, False],
    )
    next_page: int | None = Field(
        default=None,
        description="Numéro de la page suivante (None si dernière page).",
        examples=[2, 3, None],
    )
    prev_page: int | None = Field(
        default=None,
        description="Numéro de la page précédente (None si première page).",
        examples=[1, 4, None],
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper pour les réponses paginées."""

    status: str = Field(
        default="success",
        description="Statut de la réponse (toujours 'success' pour les listes).",
        examples=["success"],
    )
    data: list[T] = Field(
        description="Liste des éléments de la page actuelle.",
    )
    pagination: PaginationInfo = Field(
        description="Informations de pagination.",
    )
    metadata: ResponseMetadata = Field(
        default_factory=ResponseMetadata,
        description="Métadonnées de la réponse.",
    )


def success_response(
    data: T,
    metadata: ResponseMetadata | None = None,
    links: dict[str, str] | None = None,
) -> ApiResponse[T]:
    """Factory pour créer une réponse de succès."""
    if metadata is None:
        metadata = ResponseMetadata()
    if links:
        metadata.links = links
    return ApiResponse(status="success", data=data, metadata=metadata)


def error_response(
    error_type: str,
    message: str,
    field: str | None = None,
    metadata: ResponseMetadata | None = None,
) -> ApiResponse[None]:
    """Factory pour créer une réponse d'erreur."""
    if metadata is None:
        metadata = ResponseMetadata()
    return ApiResponse(
        status="error",
        error=ErrorDetail(type=error_type, message=message, field=field),
        metadata=metadata,
    )


def paginated_response(
    data: list[T],
    total: int,
    page: int = 1,
    per_page: int = 20,
    metadata: ResponseMetadata | None = None,
    links: dict[str, str] | None = None,
) -> PaginatedResponse[T]:
    """Factory pour créer une réponse paginée."""
    if metadata is None:
        metadata = ResponseMetadata()
    if links:
        metadata.links = links

    pages = (total + per_page - 1) // per_page  # Ceiling division
    has_next = page < pages
    has_prev = page > 1

    pagination = PaginationInfo(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        has_next=has_next,
        has_prev=has_prev,
        next_page=page + 1 if has_next else None,
        prev_page=page - 1 if has_prev else None,
    )

    return PaginatedResponse(
        status="success",
        data=data,
        pagination=pagination,
        metadata=metadata,
    )

