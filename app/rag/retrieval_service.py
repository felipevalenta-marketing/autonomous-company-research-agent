"""Semantic retrieval orchestration for company-scoped Pinecone search."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from app.clients.pinecone_dtos import PineconeQueryResponseDTO
from app.models.company import ResolvedCompany
from app.models.providers import RAGResult
from app.services.embedding_service import (
    EmbeddingServiceError,
    EmbeddingServiceResult,
)
from app.services.vector_preparation_service import VectorPreparationInputError, build_pinecone_namespace
from app.services.vector_query_service import VectorQueryError

from .normalization import (
    RAGMetadataError,
    RAGNormalizationError,
    RAGScoreError,
    normalize_rag_results,
)


class RAGRetrievalError(Exception):
    """Base exception for semantic retrieval failures."""


class RAGRetrievalInputError(RAGRetrievalError):
    """Raised when retrieval inputs are invalid."""


class RAGEmbeddingError(RAGRetrievalError):
    """Raised when query embedding fails."""


class RAGQueryError(RAGRetrievalError):
    """Raised when Pinecone retrieval fails."""


class RAGQueryResponseConsistencyError(RAGQueryError):
    """Raised when a Pinecone query response does not satisfy the approved contract."""


class RAGQueryNamespaceConsistencyError(RAGQueryError):
    """Raised when a Pinecone query response namespace does not match the requested namespace."""


def retrieve_rag_results(
    query: str,
    resolved_company: ResolvedCompany,
    embedding_service: Callable[[str], EmbeddingServiceResult],
    vector_query_service: Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
    *,
    top_k: int,
    metadata_filter: Mapping[str, object] | None = None,
    namespace_prefix: str | None = None,
) -> tuple[RAGResult, ...]:
    """Embed a query, retrieve Pinecone matches, and normalize them into RAG results."""

    trimmed_query = _normalize_query(query)
    _require_resolved_company(resolved_company)
    _require_positive_int(top_k, "top_k")

    try:
        embedding_result = embedding_service(trimmed_query)
    except EmbeddingServiceError as exc:
        raise RAGEmbeddingError("RAG query embedding failed.") from exc

    query_vector = _extract_single_embedding(embedding_result)
    try:
        namespace = build_pinecone_namespace(resolved_company, namespace_prefix)
    except VectorPreparationInputError as exc:
        raise RAGRetrievalInputError("RAG company namespace could not be constructed.") from exc

    try:
        query_response = vector_query_service(query_vector, namespace, top_k, metadata_filter)
    except VectorQueryError as exc:
        raise RAGQueryError("RAG Pinecone query failed.") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGQueryError("RAG Pinecone query failed.") from exc

    if not isinstance(query_response, PineconeQueryResponseDTO):
        raise RAGQueryResponseConsistencyError("RAG Pinecone query returned an invalid response object.")
    if query_response.namespace is not None and query_response.namespace != namespace:
        raise RAGQueryNamespaceConsistencyError("RAG Pinecone query returned a mismatched namespace.")

    try:
        return normalize_rag_results(resolved_company, query_response, retrieval_scope=namespace)
    except (RAGNormalizationError, RAGMetadataError, RAGScoreError) as exc:
        raise RAGRetrievalError("RAG retrieval normalization failed.") from exc


def _normalize_query(query: object) -> str:
    if not isinstance(query, str):
        raise RAGRetrievalInputError("query must be a string.")
    trimmed = query.strip()
    if not trimmed:
        raise RAGRetrievalInputError("query must not be empty.")
    return trimmed


def _require_resolved_company(resolved_company: object) -> None:
    if not isinstance(resolved_company, ResolvedCompany):
        raise RAGRetrievalInputError("resolved_company must be a ResolvedCompany instance.")


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RAGRetrievalInputError(f"{field_name} must be an integer.")
    if value <= 0:
        raise RAGRetrievalInputError(f"{field_name} must be positive.")
    return value


def _extract_single_embedding(embedding_result: object) -> tuple[float, ...]:
    if not isinstance(embedding_result, EmbeddingServiceResult):
        raise RAGEmbeddingError("RAG embedding service returned an invalid result object.")
    embeddings = tuple(embedding_result.embeddings)
    if len(embeddings) != 1:
        raise RAGEmbeddingError("RAG retrieval requires exactly one embedding record.")

    embedding = embeddings[0]
    if embedding.input_index != 0:
        raise RAGEmbeddingError("RAG retrieval requires the embedding input index to be zero.")
    if not embedding.vector:
        raise RAGEmbeddingError("RAG retrieval requires a non-empty query vector.")
    return embedding.vector
