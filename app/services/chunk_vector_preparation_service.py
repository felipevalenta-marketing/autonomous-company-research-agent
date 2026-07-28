"""Deterministic preparation of embedded chunks for Pinecone."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.models.chunks import ChunkRecord
from app.models.company import ResolvedCompany
from app.services.chunk_embedding_service import EmbeddedChunkRecord
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceResult
from app.services.vector_preparation_service import (
    VectorDimensionError,
    VectorMetadataError,
    VectorPreparationInputError,
    build_pinecone_namespace,
    prepare_pinecone_vectors,
)


class ChunkVectorPreparationError(Exception):
    """Base exception for chunk vector preparation failures."""


class ChunkVectorPreparationInputError(ChunkVectorPreparationError):
    """Raised when chunk vector preparation inputs are invalid."""


class ChunkVectorPreparationMappingError(ChunkVectorPreparationError):
    """Raised when embedded chunks cannot be mapped into vector records."""


@dataclass(frozen=True, slots=True)
class _NormalizedEmbeddedChunk:
    chunk: ChunkRecord
    embedding: EmbeddingRecord


class ChunkVectorPreparationServiceProtocol(Protocol):
    """Callable boundary for deterministic vector preparation."""

    def __call__(
        self,
        embedding_result: EmbeddingServiceResult,
        record_identities: Sequence[str],
        metadata_entries: Sequence[Mapping[str, object]],
        *,
        expected_dimension: int | None = None,
    ) -> tuple[PineconeVectorRecordDTO, ...]:
        """Prepare Pinecone-ready vector records."""


def prepare_chunk_vectors(
    embedded_chunks: tuple[EmbeddedChunkRecord, ...],
    *,
    resolved_company: ResolvedCompany | None = None,
    namespace_prefix: str | None = None,
    vector_preparation_service: ChunkVectorPreparationServiceProtocol = prepare_pinecone_vectors,
) -> tuple[PineconeVectorRecordDTO, ...]:
    """Prepare immutable Pinecone-ready vector records from embedded chunks."""

    normalized_chunks = _normalize_embedded_chunks(embedded_chunks)
    if not normalized_chunks:
        return ()

    if resolved_company is not None:
        try:
            _prepare_namespace(resolved_company, namespace_prefix)
        except VectorPreparationInputError as exc:
            raise ChunkVectorPreparationInputError("resolved_company must be a ResolvedCompany instance.") from exc

    embedding_result = _build_embedding_result(normalized_chunks)
    record_identities = tuple(chunk.chunk.chunk_id for chunk in normalized_chunks)
    metadata_entries = tuple(_build_metadata(chunk) for chunk in normalized_chunks)

    try:
        prepared_records = vector_preparation_service(
            embedding_result,
            record_identities,
            metadata_entries,
        )
    except (VectorPreparationInputError, VectorMetadataError, VectorDimensionError) as exc:
        raise ChunkVectorPreparationMappingError("chunk vector preparation failed.") from exc
    except ChunkVectorPreparationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ChunkVectorPreparationError("chunk vector preparation failed.") from exc

    normalized_records = _normalize_prepared_records(prepared_records, normalized_chunks)
    return normalized_records


def _normalize_embedded_chunks(
    embedded_chunks: object,
) -> tuple[_NormalizedEmbeddedChunk, ...]:
    if not isinstance(embedded_chunks, tuple):
        raise ChunkVectorPreparationInputError("embedded_chunks must be an immutable tuple of EmbeddedChunkRecord instances.")
    if not embedded_chunks:
        return ()

    normalized: list[_NormalizedEmbeddedChunk] = []
    seen_chunk_ids: set[str] = set()
    seen_embedding_indexes: set[int] = set()
    for index, embedded_chunk in enumerate(embedded_chunks):
        if not isinstance(embedded_chunk, EmbeddedChunkRecord):
            raise ChunkVectorPreparationInputError("embedded_chunks must contain EmbeddedChunkRecord instances.")
        if not isinstance(embedded_chunk.chunk, ChunkRecord):
            raise ChunkVectorPreparationInputError("embedded chunks must contain valid ChunkRecord instances.")
        if not isinstance(embedded_chunk.embedding, EmbeddingRecord):
            raise ChunkVectorPreparationInputError("embedded chunks must contain valid EmbeddingRecord instances.")
        if not isinstance(embedded_chunk.chunk.chunk_id, str) or not embedded_chunk.chunk.chunk_id.strip():
            raise ChunkVectorPreparationInputError("chunk_id must not be empty.")
        if embedded_chunk.chunk.chunk_id in seen_chunk_ids:
            raise ChunkVectorPreparationInputError("chunk_id values must be unique.")
        if isinstance(embedded_chunk.embedding.input_index, bool) or not isinstance(embedded_chunk.embedding.input_index, int):
            raise ChunkVectorPreparationInputError("embedding input indexes must be integers.")
        if embedded_chunk.embedding.input_index in seen_embedding_indexes:
            raise ChunkVectorPreparationInputError("embedding input indexes must be unique.")
        if embedded_chunk.embedding.input_index != index:
            raise ChunkVectorPreparationInputError("embedded chunks must preserve input ordering.")
        if embedded_chunk.chunk.chunk_index != index:
            raise ChunkVectorPreparationInputError("chunk indexes must preserve input ordering.")
        if not isinstance(embedded_chunk.embedding.vector, tuple) or not embedded_chunk.embedding.vector:
            raise ChunkVectorPreparationInputError("embedding vectors must not be empty.")
        seen_chunk_ids.add(embedded_chunk.chunk.chunk_id)
        seen_embedding_indexes.add(embedded_chunk.embedding.input_index)
        normalized.append(_NormalizedEmbeddedChunk(chunk=embedded_chunk.chunk, embedding=embedded_chunk.embedding))

    return tuple(normalized)


def _build_embedding_result(
    embedded_chunks: tuple[_NormalizedEmbeddedChunk, ...],
) -> EmbeddingServiceResult:
    try:
        return EmbeddingServiceResult(
            model=embedded_chunks[0].embedding.model,
            embeddings=tuple(chunk.embedding for chunk in embedded_chunks),
        )
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ChunkVectorPreparationInputError("embedded chunk embeddings could not be validated.") from exc


def _build_metadata(chunk: _NormalizedEmbeddedChunk) -> dict[str, object]:
    metadata: dict[str, object] = {
        "chunk_id": chunk.chunk.chunk_id,
        "document_id": chunk.chunk.document_id,
        "source_id": chunk.chunk.source_id,
        "company_name": chunk.chunk.company_name,
        "text_id": chunk.chunk.text,
        "content_checksum": chunk.chunk.content_checksum,
    }
    if chunk.chunk.document_type:
        metadata["filing_form"] = chunk.chunk.document_type
    if chunk.chunk.source_url:
        metadata["source_url"] = chunk.chunk.source_url
    if chunk.chunk.filing_date:
        metadata["filing_date"] = chunk.chunk.filing_date
    return metadata


def _normalize_prepared_records(
    prepared_records: object,
    normalized_chunks: tuple[_NormalizedEmbeddedChunk, ...],
) -> tuple[PineconeVectorRecordDTO, ...]:
    if not isinstance(prepared_records, tuple):
        raise ChunkVectorPreparationMappingError("prepared vector records must be returned as a tuple.")
    if len(prepared_records) != len(normalized_chunks):
        raise ChunkVectorPreparationMappingError("prepared vector record count must match the embedded chunk count.")

    normalized: list[PineconeVectorRecordDTO] = []
    for embedded_chunk, prepared_record in zip(normalized_chunks, prepared_records, strict=True):
        if not isinstance(prepared_record, PineconeVectorRecordDTO):
            raise ChunkVectorPreparationMappingError("prepared vector records must contain PineconeVectorRecordDTO instances.")
        if prepared_record.values != embedded_chunk.embedding.vector:
            raise ChunkVectorPreparationMappingError("prepared vector values must preserve the embedded chunk vector.")
        if prepared_record.metadata.get("chunk_id") != embedded_chunk.chunk.chunk_id:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve chunk identity.")
        if prepared_record.metadata.get("document_id") != embedded_chunk.chunk.document_id:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve document identity.")
        if prepared_record.metadata.get("source_id") != embedded_chunk.chunk.source_id:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve source identity.")
        if prepared_record.metadata.get("company_name") != embedded_chunk.chunk.company_name:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve company identity.")
        if prepared_record.metadata.get("filing_form") != embedded_chunk.chunk.document_type:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve the chunk document type.")
        if prepared_record.metadata.get("text_id") != embedded_chunk.chunk.text:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve chunk text.")
        if prepared_record.metadata.get("content_checksum") != embedded_chunk.chunk.content_checksum:
            raise ChunkVectorPreparationMappingError("prepared vector metadata must preserve the chunk checksum.")
        normalized.append(prepared_record)

    return tuple(normalized)


def _prepare_namespace(
    resolved_company: ResolvedCompany,
    namespace_prefix: str | None = None,
) -> str:
    return build_pinecone_namespace(resolved_company, namespace_prefix)
