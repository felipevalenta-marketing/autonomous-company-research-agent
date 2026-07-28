"""Deterministic orchestration for query-time RAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from app.clients.pinecone_dtos import PineconeQueryResponseDTO
from app.models.company import ResolvedCompany
from app.models.providers import RAGResult
from app.rag.retrieval_service import (
    RAGEmbeddingError,
    RAGRetrievalError,
    RAGRetrievalInputError,
    retrieve_rag_results,
)
from app.services.embedding_service import EmbeddingServiceResult


class RAGQueryError(Exception):
    """Base exception for RAG query orchestration failures."""


class RAGQueryInputError(RAGQueryError):
    """Raised when query orchestration inputs are invalid."""


class RAGQueryConsistencyError(RAGQueryError):
    """Raised when query orchestration outputs are malformed."""


@dataclass(frozen=True, slots=True)
class RAGQueryResult:
    """Immutable query orchestration result."""

    query: str
    results: tuple[RAGResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must not be empty.")
        if not isinstance(self.results, tuple):
            raise ValueError("results must be a tuple of RAGResult instances.")
        for result in self.results:
            if not isinstance(result, RAGResult):
                raise ValueError("results must contain RAGResult instances.")


class RAGRetrievalServiceProtocol(Protocol):
    """Callable boundary for approved RAG retrieval orchestration."""

    def __call__(
        self,
        query: str,
        resolved_company: ResolvedCompany,
        embedding_service: Callable[[str], EmbeddingServiceResult],
        vector_query_service: Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
        *,
        top_k: int,
        metadata_filter: Mapping[str, object] | None = None,
        namespace_prefix: str | None = None,
    ) -> tuple[RAGResult, ...]:
        """Retrieve normalized RAG results for a single company query."""


def query_company_rag(
    query: str,
    resolved_company: ResolvedCompany,
    embedding_service: Callable[[str], EmbeddingServiceResult],
    vector_query_service: Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
    *,
    top_k: int,
    metadata_filter: Mapping[str, object] | None = None,
    namespace_prefix: str | None = None,
    retrieval_service: RAGRetrievalServiceProtocol = retrieve_rag_results,
) -> RAGQueryResult:
    """Validate a query and delegate to the approved RAG retrieval boundary."""

    normalized_query = _normalize_query(query)
    _require_resolved_company(resolved_company)
    _require_positive_int(top_k, "top_k")

    try:
        results = retrieval_service(
            normalized_query,
            resolved_company,
            embedding_service,
            vector_query_service,
            top_k=top_k,
            metadata_filter=metadata_filter,
            namespace_prefix=namespace_prefix,
        )
    except RAGRetrievalInputError as exc:
        raise RAGQueryInputError("RAG query inputs are invalid.") from exc
    except (RAGEmbeddingError, RAGRetrievalError):
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGQueryError("RAG query orchestration failed.") from exc

    normalized_results = _normalize_results(results)
    return RAGQueryResult(query=query, results=normalized_results)


def _normalize_query(query: object) -> str:
    if not isinstance(query, str):
        raise RAGQueryInputError("query must be a string.")
    trimmed = query.strip()
    if not trimmed:
        raise RAGQueryInputError("query must not be empty.")
    return query


def _require_resolved_company(resolved_company: object) -> None:
    if not isinstance(resolved_company, ResolvedCompany):
        raise RAGQueryInputError("resolved_company must be a ResolvedCompany instance.")


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RAGQueryInputError(f"{field_name} must be an integer.")
    if value <= 0:
        raise RAGQueryInputError(f"{field_name} must be positive.")
    return value


def _normalize_results(results: object) -> tuple[RAGResult, ...]:
    if not isinstance(results, tuple):
        raise RAGQueryConsistencyError("RAG retrieval must return a tuple of RAGResult instances.")
    normalized: list[RAGResult] = []
    for result in results:
        if not isinstance(result, RAGResult):
            raise RAGQueryConsistencyError("RAG retrieval must return RAGResult instances.")
        normalized.append(result)
    return tuple(normalized)
