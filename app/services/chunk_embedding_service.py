"""Deterministic orchestration for embedding document chunks."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.models.chunks import ChunkRecord
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceError, EmbeddingServiceResult
from app.utils.hashing import sha256_text


class ChunkEmbeddingError(Exception):
    """Base exception for chunk embedding failures."""


class ChunkEmbeddingInputError(ChunkEmbeddingError):
    """Raised when chunk embedding inputs are invalid."""


class ChunkEmbeddingResultError(ChunkEmbeddingError):
    """Raised when the embedding service returns an invalid result."""


class ChunkEmbeddingMappingError(ChunkEmbeddingError):
    """Raised when embedding records cannot be mapped to chunks."""


@dataclass(frozen=True, slots=True)
class EmbeddedChunkRecord:
    """Immutable chunk and embedding pair."""

    chunk: ChunkRecord
    embedding: EmbeddingRecord

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, ChunkRecord):
            raise ValueError("chunk must be a ChunkRecord instance.")
        if not isinstance(self.embedding, EmbeddingRecord):
            raise ValueError("embedding must be an EmbeddingRecord instance.")
        if self.embedding.input_index != self.chunk.chunk_index:
            raise ValueError("embedding input_index must match the chunk index.")
        if self.embedding.input_checksum != sha256_text(self.chunk.text):
            raise ValueError("embedding checksum must match the chunk text.")


class ChunkEmbeddingServiceProtocol(Protocol):
    """Callable embedding service boundary used by chunk embedding orchestration."""

    def __call__(self, texts: tuple[str, ...]) -> EmbeddingServiceResult:
        """Embed a tuple of texts and return a validated embedding result."""


def embed_chunks(
    chunks: tuple[ChunkRecord, ...],
    embedding_service: ChunkEmbeddingServiceProtocol,
) -> tuple[EmbeddedChunkRecord, ...]:
    """Embed canonical chunks into immutable embedded chunk records."""

    normalized_chunks = _normalize_chunks(chunks)
    if not normalized_chunks:
        return ()

    chunk_texts = tuple(chunk.text for chunk in normalized_chunks)
    try:
        embedding_result = embedding_service(chunk_texts)
    except EmbeddingServiceError as exc:
        raise ChunkEmbeddingError("chunk embedding failed.") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ChunkEmbeddingError("chunk embedding failed.") from exc

    embeddings_by_index, response_model = _normalize_embedding_result(
        embedding_result,
        expected_count=len(normalized_chunks),
    )

    embedded_chunks: list[EmbeddedChunkRecord] = []
    for chunk in normalized_chunks:
        embedding = embeddings_by_index[chunk.chunk_index]
        if embedding.input_checksum != sha256_text(chunk.text):
            raise ChunkEmbeddingMappingError("embedding input checksum did not match the chunk text.")
        if embedding.model != response_model:
            raise ChunkEmbeddingResultError("embedding model must remain consistent across the result.")
        embedded_chunks.append(EmbeddedChunkRecord(chunk=chunk, embedding=embedding))

    return tuple(embedded_chunks)


def _normalize_chunks(chunks: object) -> tuple[ChunkRecord, ...]:
    if not isinstance(chunks, tuple):
        raise ChunkEmbeddingInputError("chunks must be an immutable tuple of ChunkRecord instances.")

    if not chunks:
        return ()

    normalized: list[ChunkRecord] = []
    seen_chunk_ids: set[str] = set()
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, ChunkRecord):
            raise ChunkEmbeddingInputError("chunks must contain ChunkRecord instances.")
        if not isinstance(chunk.chunk_id, str) or not chunk.chunk_id.strip():
            raise ChunkEmbeddingInputError("chunk_id must not be empty.")
        if not isinstance(chunk.text, str) or not chunk.text.strip():
            raise ChunkEmbeddingInputError("chunk text must not be empty.")
        if isinstance(chunk.chunk_index, bool) or not isinstance(chunk.chunk_index, int):
            raise ChunkEmbeddingInputError("chunk indexes must be integers.")
        if chunk.chunk_index != index:
            raise ChunkEmbeddingInputError("chunk indexes must preserve the input ordering.")
        if chunk.chunk_id in seen_chunk_ids:
            raise ChunkEmbeddingInputError("chunk_id values must be unique.")
        seen_chunk_ids.add(chunk.chunk_id)
        normalized.append(chunk)

    return tuple(normalized)


def _normalize_embedding_result(
    embedding_result: object,
    *,
    expected_count: int,
) -> tuple[dict[int, EmbeddingRecord], str]:
    if not isinstance(embedding_result, EmbeddingServiceResult):
        raise ChunkEmbeddingResultError("embedding service returned an invalid result object.")

    model = embedding_result.model.strip() if isinstance(embedding_result.model, str) else ""
    if not model:
        raise ChunkEmbeddingResultError("embedding result model must not be empty.")

    embeddings = embedding_result.embeddings
    if not isinstance(embeddings, tuple):
        raise ChunkEmbeddingResultError("embedding results must be a tuple of EmbeddingRecord instances.")
    if len(embeddings) != expected_count:
        raise ChunkEmbeddingResultError("embedding result count must match the chunk count.")

    embeddings_by_index: dict[int, EmbeddingRecord] = {}
    for embedding in embeddings:
        _validate_embedding_record(embedding, expected_count=expected_count)
        if embedding.model != model:
            raise ChunkEmbeddingResultError("embedding model must remain consistent across the result.")
        if embedding.input_index in embeddings_by_index:
            raise ChunkEmbeddingResultError("embedding input indexes must be unique.")
        embeddings_by_index[embedding.input_index] = embedding

    if set(embeddings_by_index) != set(range(expected_count)):
        raise ChunkEmbeddingResultError("embedding input indexes must cover the full chunk collection.")

    return embeddings_by_index, model


def _validate_embedding_record(embedding: object, *, expected_count: int) -> None:
    if not isinstance(embedding, EmbeddingRecord):
        raise ChunkEmbeddingResultError("embedding results must contain EmbeddingRecord instances.")
    if isinstance(embedding.input_index, bool) or not isinstance(embedding.input_index, int):
        raise ChunkEmbeddingResultError("embedding input indexes must be integers.")
    if embedding.input_index < 0:
        raise ChunkEmbeddingResultError("embedding input indexes must be zero or positive.")
    if embedding.input_index >= expected_count:
        raise ChunkEmbeddingResultError("embedding input indexes must stay within the chunk collection.")
    if not isinstance(embedding.input_checksum, str) or not embedding.input_checksum.strip():
        raise ChunkEmbeddingResultError("embedding checksums must not be empty.")
    if not isinstance(embedding.model, str) or not embedding.model.strip():
        raise ChunkEmbeddingResultError("embedding model must not be empty.")
    if isinstance(embedding.vector_dimension, bool) or not isinstance(embedding.vector_dimension, int):
        raise ChunkEmbeddingResultError("embedding vector dimensions must be integers.")
    if embedding.vector_dimension <= 0:
        raise ChunkEmbeddingResultError("embedding vector dimensions must be positive.")
    if not isinstance(embedding.vector, tuple) or not embedding.vector:
        raise ChunkEmbeddingResultError("embedding vectors must be non-empty tuples.")
    if len(embedding.vector) != embedding.vector_dimension:
        raise ChunkEmbeddingResultError("embedding vector dimensions must match the vector length.")
    for value in embedding.vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ChunkEmbeddingResultError("embedding vectors must contain numeric values.")
        numeric = float(value)
        if not isfinite(numeric):
            raise ChunkEmbeddingResultError("embedding vectors must contain finite values.")
