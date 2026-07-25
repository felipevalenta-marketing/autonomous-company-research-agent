"""Application-service orchestration for OpenAI embeddings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.clients.openai_embeddings_client import (
    OpenAIEmbeddingsPayloadError,
    OpenAIEmbeddingsResponseValidationError,
)
from app.config.constants import OPENAI_DEFAULT_EMBEDDING_MODEL, OPENAI_MAX_EMBEDDING_BATCH_SIZE
from app.utils.hashing import sha256_text


class EmbeddingServiceError(Exception):
    """Base exception for embedding service failures."""


class EmbeddingInputError(EmbeddingServiceError):
    """Raised when the embedding service receives invalid input."""


class EmbeddingBatchError(EmbeddingServiceError):
    """Raised when a batch response does not match the request batch."""


class EmbeddingDimensionError(EmbeddingServiceError):
    """Raised when embedding dimensions are inconsistent or unexpected."""


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    """Immutable traceable embedding result."""

    input_index: int
    input_checksum: str
    model: str
    vector_dimension: int
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if isinstance(self.input_index, bool) or not isinstance(self.input_index, int) or self.input_index < 0:
            raise ValueError("input_index must be a zero or positive integer.")
        if not isinstance(self.input_checksum, str) or not self.input_checksum.strip():
            raise ValueError("input_checksum must not be empty.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must not be empty.")
        if isinstance(self.vector_dimension, bool) or not isinstance(self.vector_dimension, int) or self.vector_dimension <= 0:
            raise ValueError("vector_dimension must be a positive integer.")
        if not isinstance(self.vector, tuple) or not self.vector:
            raise ValueError("vector must be a non-empty tuple.")
        if len(self.vector) != self.vector_dimension:
            raise ValueError("vector_dimension must match the vector length.")
        for value in self.vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("vector values must be numeric.")
            numeric = float(value)
            if not isfinite(numeric):
                raise ValueError("vector values must be finite.")
        object.__setattr__(self, "input_checksum", self.input_checksum.strip())
        object.__setattr__(self, "model", self.model.strip())


@dataclass(frozen=True, slots=True)
class EmbeddingServiceResult:
    """Validated embedding service output."""

    model: str
    embeddings: tuple[EmbeddingRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must not be empty.")
        if not isinstance(self.embeddings, tuple):
            raise ValueError("embeddings must be a tuple of EmbeddingRecord instances.")
        if not self.embeddings:
            raise ValueError("embeddings must not be empty.")
        for embedding in self.embeddings:
            if not isinstance(embedding, EmbeddingRecord):
                raise ValueError("embeddings must contain EmbeddingRecord instances.")
        indexes = [embedding.input_index for embedding in self.embeddings]
        if indexes != list(range(len(self.embeddings))):
            raise ValueError("embeddings must preserve original input ordering.")
        if any(embedding.model != self.model.strip() for embedding in self.embeddings):
            raise ValueError("embedding models must be consistent.")
        object.__setattr__(self, "model", self.model.strip())


class EmbeddingClientProtocol(Protocol):
    """Minimal OpenAI embeddings client contract required by the service."""

    def create_embeddings(
        self,
        texts: str | Sequence[str],
        model: str,
        dimensions: int | None = None,
    ) -> object:
        """Return a validated OpenAI embeddings response."""


def embed_texts(
    texts: str | Sequence[str],
    embedding_client: EmbeddingClientProtocol,
    *,
    model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    batch_size: int = OPENAI_MAX_EMBEDDING_BATCH_SIZE,
    dimensions: int | None = None,
    expected_dimension: int | None = None,
) -> EmbeddingServiceResult:
    """Create deterministic embedding records for the provided texts."""

    normalized_texts = _normalize_text_inputs(texts)
    normalized_model = _normalize_model(model)
    normalized_batch_size = _normalize_batch_size(batch_size)
    normalized_dimensions = _normalize_optional_positive_int(dimensions, "dimensions")
    normalized_expected_dimension = _normalize_optional_positive_int(expected_dimension, "expected_dimension")

    if (
        normalized_dimensions is not None
        and normalized_expected_dimension is not None
        and normalized_dimensions != normalized_expected_dimension
    ):
        raise EmbeddingDimensionError("dimensions and expected_dimension must match when both are provided.")

    validation_dimension = normalized_expected_dimension if normalized_expected_dimension is not None else normalized_dimensions
    records: list[EmbeddingRecord] = []
    observed_dimension: int | None = None

    for batch_start in range(0, len(normalized_texts), normalized_batch_size):
        batch_texts = normalized_texts[batch_start : batch_start + normalized_batch_size]
        response = embedding_client.create_embeddings(batch_texts, normalized_model, normalized_dimensions)
        batch_records, batch_dimension, response_model = _normalize_batch_response(
            response=response,
            batch_texts=batch_texts,
            batch_start=batch_start,
            requested_model=normalized_model,
            validation_dimension=validation_dimension,
        )
        if observed_dimension is None:
            observed_dimension = batch_dimension
        elif observed_dimension != batch_dimension:
            raise EmbeddingDimensionError("embedding dimensions must remain consistent across batches.")
        records.extend(batch_records)
        normalized_model = response_model

    return EmbeddingServiceResult(model=normalized_model, embeddings=tuple(records))


def _normalize_batch_response(
    *,
    response: object,
    batch_texts: tuple[str, ...],
    batch_start: int,
    requested_model: str,
    validation_dimension: int | None,
) -> tuple[list[EmbeddingRecord], int, str]:
    model = getattr(response, "model", None)
    if not isinstance(model, str) or not model.strip():
        raise EmbeddingBatchError("embedding response must include a non-empty model value.")
    model = model.strip()
    if model != requested_model:
        raise EmbeddingBatchError("embedding response model did not match the request.")

    data = getattr(response, "data", None)
    if not isinstance(data, (list, tuple)):
        raise EmbeddingBatchError("embedding response must include a data collection.")
    if len(data) != len(batch_texts):
        raise EmbeddingBatchError("embedding response count must match the request batch.")

    usage = getattr(response, "usage", None)
    if usage is None:
        raise EmbeddingBatchError("embedding response must include usage metadata.")

    records: list[EmbeddingRecord] = []
    expected_indexes = list(range(len(batch_texts)))
    batch_dimension: int | None = None
    for local_index, item in enumerate(tuple(data)):
        item_index = getattr(item, "index", None)
        if item_index != expected_indexes[local_index]:
            raise EmbeddingBatchError("embedding response indexes must match the request batch order.")

        vector = getattr(item, "embedding", None)
        if not isinstance(vector, tuple):
            vector = tuple(vector) if isinstance(vector, list) else vector
        if not isinstance(vector, tuple) or not vector:
            raise EmbeddingBatchError("embedding vectors must be non-empty tuples.")

        normalized_vector = _normalize_vector(vector)
        vector_dimension = len(normalized_vector)
        if batch_dimension is None:
            batch_dimension = vector_dimension
        elif batch_dimension != vector_dimension:
            raise EmbeddingDimensionError("embedding vectors must share the same dimension within a batch.")
        if validation_dimension is not None and vector_dimension != validation_dimension:
            raise EmbeddingDimensionError("embedding vector dimension did not match the configured expectation.")

        checksum = sha256_text(batch_texts[local_index])
        records.append(
            EmbeddingRecord(
                input_index=batch_start + local_index,
                input_checksum=checksum,
                model=model,
                vector_dimension=vector_dimension,
                vector=normalized_vector,
            )
        )

    if batch_dimension is None:
        raise EmbeddingBatchError("embedding response must include at least one vector.")
    return records, batch_dimension, model


def _normalize_text_inputs(texts: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(texts, str):
        normalized = (texts,)
    else:
        try:
            normalized = tuple(texts)
        except TypeError as exc:
            raise EmbeddingInputError("texts must be a string or an ordered collection of strings.") from exc
    if not normalized:
        raise EmbeddingInputError("texts must not be empty.")
    result: list[str] = []
    for text in normalized:
        if not isinstance(text, str):
            raise EmbeddingInputError("texts must contain only strings.")
        if not text.strip():
            raise EmbeddingInputError("texts must not contain blank strings.")
        result.append(text)
    return tuple(result)


def _normalize_model(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingInputError("model must not be empty.")
    return value.strip()


def _normalize_batch_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EmbeddingBatchError("batch_size must be an integer.")
    if value <= 0:
        raise EmbeddingBatchError("batch_size must be positive.")
    return min(value, OPENAI_MAX_EMBEDDING_BATCH_SIZE)


def _normalize_optional_positive_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EmbeddingDimensionError(f"{field_name} must be an integer when provided.")
    if value <= 0:
        raise EmbeddingDimensionError(f"{field_name} must be positive when provided.")
    return value


def _normalize_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingBatchError("embedding values must be numeric.")
        numeric = float(value)
        if not isfinite(numeric):
            raise EmbeddingBatchError("embedding values must be finite.")
        normalized.append(numeric)
    if not normalized:
        raise EmbeddingBatchError("embedding vectors must not be empty.")
    return tuple(normalized)
