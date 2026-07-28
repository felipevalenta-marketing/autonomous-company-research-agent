"""Deterministic orchestration for indexing prepared chunk vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.clients.pinecone_client import PineconeClientProtocol
from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.services.vector_indexing_service import (
    VectorBatchError,
    VectorIndexingError,
    VectorIndexingResult,
    index_pinecone_vectors,
)


class ChunkVectorIndexingError(Exception):
    """Base exception for chunk vector indexing failures."""


class ChunkVectorIndexingInputError(ChunkVectorIndexingError):
    """Raised when chunk vector indexing inputs are invalid."""


class ChunkVectorIndexingServiceProtocol(Protocol):
    """Callable boundary for deterministic prepared-vector indexing."""

    def __call__(
        self,
        records: Sequence[PineconeVectorRecordDTO],
        pinecone_client: PineconeClientProtocol,
        namespace: str,
        pinecone_config: PineconeConfig,
        *,
        batch_size: int | None = None,
    ) -> VectorIndexingResult:
        """Index Pinecone-ready vector records."""


def index_chunk_vectors(
    prepared_vectors: tuple[PineconeVectorRecordDTO, ...],
    pinecone_client: PineconeClientProtocol,
    namespace: str,
    pinecone_config: PineconeConfig,
    *,
    batch_size: int | None = None,
    vector_indexing_service: ChunkVectorIndexingServiceProtocol = index_pinecone_vectors,
) -> VectorIndexingResult:
    """Index prepared chunk vectors through the existing Pinecone boundary."""

    normalized_vectors = _normalize_prepared_vectors(prepared_vectors)
    if not normalized_vectors:
        return _build_empty_result(namespace)

    try:
        result = vector_indexing_service(
            normalized_vectors,
            pinecone_client,
            namespace,
            pinecone_config,
            batch_size=batch_size,
        )
    except VectorIndexingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ChunkVectorIndexingError("chunk vector indexing failed.") from exc

    return _normalize_indexing_result(result, namespace, len(normalized_vectors))


def _normalize_prepared_vectors(
    prepared_vectors: object,
) -> tuple[PineconeVectorRecordDTO, ...]:
    if not isinstance(prepared_vectors, tuple):
        raise ChunkVectorIndexingInputError("prepared_vectors must be an immutable tuple of PineconeVectorRecordDTO instances.")
    if not prepared_vectors:
        return ()

    normalized: list[PineconeVectorRecordDTO] = []
    seen_record_ids: set[str] = set()
    for record in prepared_vectors:
        if not isinstance(record, PineconeVectorRecordDTO):
            raise ChunkVectorIndexingInputError("prepared_vectors must contain PineconeVectorRecordDTO instances.")
        if record.record_id in seen_record_ids:
            raise ChunkVectorIndexingInputError("prepared vector record IDs must be unique.")
        seen_record_ids.add(record.record_id)
        normalized.append(record)
    return tuple(normalized)


def _build_empty_result(namespace: str) -> VectorIndexingResult:
    try:
        return VectorIndexingResult(
            namespace=namespace,
            attempted_count=0,
            accepted_count=0,
            acknowledgements=(),
        )
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ChunkVectorIndexingInputError("namespace must be valid.") from exc


def _normalize_indexing_result(
    result: object,
    namespace: str,
    expected_count: int,
) -> VectorIndexingResult:
    if not isinstance(result, VectorIndexingResult):
        raise ChunkVectorIndexingError("vector indexing must return a VectorIndexingResult instance.")
    if result.namespace != namespace:
        raise ChunkVectorIndexingError("vector indexing result namespace must match the requested namespace.")
    if result.attempted_count != expected_count:
        raise ChunkVectorIndexingError("vector indexing result count must match the prepared vector count.")
    if result.accepted_count < 0 or result.accepted_count > result.attempted_count:
        raise ChunkVectorIndexingError("vector indexing accepted counts must be bounded by the attempted count.")
    return result
