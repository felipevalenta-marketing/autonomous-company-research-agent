"""Pinecone indexing and deletion helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.clients.pinecone_client import (
    PineconeClientError,
    PineconeClientProtocol,
    PineconeDeleteResultDTO,
    PineconeUpsertResultDTO,
    PineconeVectorRecordDTO,
)
from app.config.defaults import PineconeConfig
from app.services.vector_preparation_service import VectorDimensionError


class VectorIndexingError(Exception):
    """Base exception for Pinecone indexing failures."""


class VectorBatchError(VectorIndexingError):
    """Raised when a vector batch cannot be indexed."""


class VectorDeletionError(VectorIndexingError):
    """Raised when a Pinecone delete operation fails."""


@dataclass(frozen=True, slots=True)
class VectorIndexingResult:
    """Immutable indexing result summary."""

    namespace: str
    attempted_count: int
    accepted_count: int
    acknowledgements: tuple[PineconeUpsertResultDTO, ...]

    def __post_init__(self) -> None:
        _require_namespace(self.namespace)
        if isinstance(self.attempted_count, bool) or not isinstance(self.attempted_count, int) or self.attempted_count < 0:
            raise ValueError("attempted_count must be a zero or positive integer.")
        if isinstance(self.accepted_count, bool) or not isinstance(self.accepted_count, int) or self.accepted_count < 0:
            raise ValueError("accepted_count must be a zero or positive integer.")
        if not isinstance(self.acknowledgements, tuple):
            raise ValueError("acknowledgements must be a tuple of PineconeUpsertResultDTO instances.")
        for acknowledgement in self.acknowledgements:
            if not isinstance(acknowledgement, PineconeUpsertResultDTO):
                raise ValueError("acknowledgements must contain PineconeUpsertResultDTO instances.")


def index_pinecone_vectors(
    records: Sequence[PineconeVectorRecordDTO],
    pinecone_client: PineconeClientProtocol,
    namespace: str,
    pinecone_config: PineconeConfig,
    *,
    batch_size: int | None = None,
) -> VectorIndexingResult:
    """Index prepared Pinecone vector records in deterministic batches."""

    if isinstance(records, str):
        raise VectorIndexingError("records must be an ordered collection of PineconeVectorRecordDTO instances.")

    normalized_namespace = _require_namespace(namespace)
    normalized_records = tuple(records)
    if not normalized_records:
        raise VectorIndexingError("records must not be empty.")

    normalized_batch_size = _normalize_batch_size(batch_size, pinecone_config.max_upsert_batch_size)
    expected_dimension = _normalize_positive_int(pinecone_config.vector_dimension, "vector_dimension")
    acknowledgements: list[PineconeUpsertResultDTO] = []
    accepted_count = 0

    for batch_start in range(0, len(normalized_records), normalized_batch_size):
        batch_records = normalized_records[batch_start : batch_start + normalized_batch_size]
        _validate_vector_batch(batch_records, expected_dimension)
        try:
            acknowledgement = pinecone_client.upsert(batch_records, normalized_namespace)
        except PineconeClientError as exc:
            raise VectorBatchError("Pinecone vector batch indexing failed.") from exc
        acknowledgements.append(acknowledgement)
        accepted_count += acknowledgement.upserted_count

    try:
        return VectorIndexingResult(
            namespace=normalized_namespace,
            attempted_count=len(normalized_records),
            accepted_count=accepted_count,
            acknowledgements=tuple(acknowledgements),
        )
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise VectorIndexingError("Pinecone indexing result could not be validated.") from exc


def delete_pinecone_vectors(
    pinecone_client: PineconeClientProtocol,
    namespace: str,
    *,
    ids: Sequence[str] | None = None,
    filter: Mapping[str, object] | None = None,
    delete_all: bool = False,
) -> PineconeDeleteResultDTO:
    """Delete vectors from Pinecone in a controlled fashion."""

    normalized_namespace = _require_namespace(namespace, VectorDeletionError)

    delete_modes = sum((ids is not None, filter is not None, delete_all))
    if delete_modes != 1:
        raise VectorDeletionError("delete requires exactly one deletion mode.")

    normalized_ids: tuple[str, ...] | None = None
    if ids is not None:
        normalized_ids = _normalize_ids(ids)
    normalized_filter = _normalize_filter(filter)

    try:
        return pinecone_client.delete(
            normalized_namespace,
            ids=normalized_ids,
            filter=normalized_filter,
            delete_all=delete_all,
        )
    except PineconeClientError as exc:
        raise VectorDeletionError("Pinecone vector deletion failed.") from exc


def _validate_vector_batch(records: tuple[PineconeVectorRecordDTO, ...], expected_dimension: int) -> None:
    for record in records:
        if record.values is None or not record.values:
            raise VectorDimensionError("vector records must contain non-empty vectors.")
        if len(record.values) != expected_dimension:
            raise VectorDimensionError("vector records must match the configured index dimension.")


def _normalize_positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorIndexingError(f"{field_name} must be an integer.")
    if value <= 0:
        raise VectorIndexingError(f"{field_name} must be positive.")
    return value


def _normalize_batch_size(value: int | None, maximum: int) -> int:
    if value is None:
        return _normalize_positive_int(maximum, "max_upsert_batch_size")
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorBatchError("batch_size must be an integer when provided.")
    if value <= 0:
        raise VectorBatchError("batch_size must be positive when provided.")
    return min(value, _normalize_positive_int(maximum, "max_upsert_batch_size"))


def _require_namespace(value: object, error_type: type[Exception] = VectorIndexingError) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type("namespace must not be empty.")
    return value.strip()


def _normalize_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise VectorDeletionError("ids must be an ordered collection of strings.")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise VectorDeletionError("ids must contain non-empty strings.")
        normalized_value = value.strip()
        if normalized_value in seen:
            raise VectorDeletionError("ids must not contain duplicates.")
        seen.add(normalized_value)
        normalized.append(normalized_value)
    if not normalized:
        raise VectorDeletionError("ids must not be empty.")
    return tuple(normalized)


def _normalize_filter(filter_value: Mapping[str, object] | None) -> dict[str, object] | None:
    if filter_value is None:
        return None
    if not isinstance(filter_value, Mapping):
        raise VectorDeletionError("filter must be a mapping when provided.")

    normalized: dict[str, object] = {}
    for key, value in filter_value.items():
        if not isinstance(key, str) or not key.strip():
            raise VectorDeletionError("filter keys must be non-empty strings.")
        if value is None:
            raise VectorDeletionError("filter values must not be null.")
        if isinstance(value, Mapping):
            raise VectorDeletionError("filter values must be simple JSON-compatible values.")
        normalized[key.strip()] = _normalize_filter_value(value)
    if not normalized:
        raise VectorDeletionError("filter must not be empty.")
    return normalized


def _normalize_filter_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise VectorDeletionError("filter numeric values must be finite.")
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise VectorDeletionError("filter string values must not be empty.")
        return stripped
    if isinstance(value, (list, tuple)):
        normalized_list: list[object] = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)) or item is None:
                raise VectorDeletionError("filter lists must be flat.")
            normalized_list.append(_normalize_filter_value(item))
        return tuple(normalized_list)
    raise VectorDeletionError("filter values must be JSON-compatible.")
