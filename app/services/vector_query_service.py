"""Pinecone vector query helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from app.clients.pinecone_client import (
    PineconeClientError,
    PineconeClientProtocol,
    PineconeQueryMatchDTO,
    PineconeQueryResponseDTO,
)
from app.config.defaults import PineconeConfig
from app.services.vector_preparation_service import VectorDimensionError


class VectorQueryError(Exception):
    """Base exception for Pinecone vector query failures."""


@dataclass(frozen=True, slots=True)
class VectorQueryResult:
    """Immutable vector query result."""

    namespace: str
    top_k: int
    matches: tuple[PineconeQueryMatchDTO, ...]

    def __post_init__(self) -> None:
        _require_namespace(self.namespace)
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k <= 0:
            raise ValueError("top_k must be a positive integer.")
        if not isinstance(self.matches, tuple):
            raise ValueError("matches must be a tuple of PineconeQueryMatchDTO instances.")
        for match in self.matches:
            if not isinstance(match, PineconeQueryMatchDTO):
                raise ValueError("matches must contain PineconeQueryMatchDTO instances.")


def query_pinecone_vectors(
    query_vector: Sequence[float],
    pinecone_client: PineconeClientProtocol,
    namespace: str,
    pinecone_config: PineconeConfig,
    *,
    top_k: int | None = None,
    filter: Mapping[str, object] | None = None,
) -> PineconeQueryResponseDTO:
    """Query Pinecone with a validated vector and deterministic ordering."""

    normalized_namespace = _require_namespace(namespace)
    normalized_vector = _normalize_vector(query_vector, pinecone_config.vector_dimension)
    normalized_top_k = _normalize_top_k(top_k, pinecone_config.max_query_top_k)
    normalized_filter = _normalize_filter(filter)

    try:
        response = pinecone_client.query(
            normalized_vector,
            normalized_namespace,
            normalized_top_k,
            filter=normalized_filter,
        )
    except PineconeClientError as exc:
        raise VectorQueryError("Pinecone vector query failed.") from exc

    sorted_matches = tuple(
        sorted(response.matches, key=lambda match: (-match.score, match.record_id))
    )
    try:
        return PineconeQueryResponseDTO(matches=sorted_matches, namespace=response.namespace or normalized_namespace)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise VectorQueryError("Pinecone query result could not be validated.") from exc


def _require_namespace(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorQueryError("namespace must not be empty.")
    return value.strip()


def _normalize_top_k(value: int | None, maximum: int) -> int:
    if value is None:
        return maximum
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorQueryError("top_k must be an integer when provided.")
    if value <= 0:
        raise VectorQueryError("top_k must be positive when provided.")
    return min(value, maximum)


def _normalize_vector(vector: Sequence[float], expected_dimension: int) -> tuple[float, ...]:
    if isinstance(vector, str):
        raise VectorQueryError("query_vector must be an ordered collection of numbers.")

    normalized: list[float] = []
    for value in tuple(vector):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise VectorQueryError("query_vector must contain numeric values.")
        numeric = float(value)
        if not isfinite(numeric):
            raise VectorQueryError("query_vector must contain finite values.")
        normalized.append(numeric)
    if not normalized:
        raise VectorQueryError("query_vector must not be empty.")
    if len(normalized) != expected_dimension:
        raise VectorDimensionError("query_vector dimension did not match the configured index dimension.")
    return tuple(normalized)


def _normalize_filter(filter_value: Mapping[str, object] | None) -> dict[str, object] | None:
    if filter_value is None:
        return None
    if not isinstance(filter_value, Mapping):
        raise VectorQueryError("filter must be a mapping when provided.")

    normalized: dict[str, object] = {}
    for key, value in filter_value.items():
        if not isinstance(key, str) or not key.strip():
            raise VectorQueryError("filter keys must be non-empty strings.")
        if value is None:
            raise VectorQueryError("filter values must not be null.")
        if isinstance(value, Mapping):
            raise VectorQueryError("filter values must be simple JSON-compatible values.")
        normalized[key.strip()] = _normalize_filter_value(value)
    if not normalized:
        raise VectorQueryError("filter must not be empty.")
    return normalized


def _normalize_filter_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise VectorQueryError("filter numeric values must be finite.")
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise VectorQueryError("filter string values must not be empty.")
        return stripped
    if isinstance(value, (list, tuple)):
        normalized_list: list[object] = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)) or item is None:
                raise VectorQueryError("filter lists must be flat.")
            normalized_list.append(_normalize_filter_value(item))
        return tuple(normalized_list)
    raise VectorQueryError("filter values must be JSON-compatible.")
