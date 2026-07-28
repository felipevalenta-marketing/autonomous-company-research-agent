"""Deterministic evidence assembly from normalized RAG results."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.models.providers import RAGResult
from app.services.rag_query_service import RAGQueryResult


class EvidenceAssemblyError(Exception):
    """Base exception for evidence assembly failures."""


class EvidenceAssemblyInputError(EvidenceAssemblyError):
    """Raised when evidence assembly inputs are invalid."""


class EvidenceAssemblyConsistencyError(EvidenceAssemblyError):
    """Raised when normalized RAG results are malformed or contradictory."""


@dataclass(frozen=True, slots=True)
class RAGEvidenceRecord:
    """Immutable traceable RAG evidence item."""

    result_id: str
    query: str
    company_name: str
    source_id: str
    document_id: str
    chunk_id: str
    text: str
    similarity_score: float | None = None
    retrieval_scope: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.result_id, "result_id")
        _require_text(self.query, "query")
        _require_text(self.company_name, "company_name")
        _require_text(self.source_id, "source_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.text, "text")
        if self.similarity_score is not None:
            _require_numeric_finite(self.similarity_score, "similarity_score")
        if self.retrieval_scope is not None:
            _require_text(self.retrieval_scope, "retrieval_scope")
        if self.source_url is not None:
            _require_text(self.source_url, "source_url")


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Immutable evidence assembly result."""

    query: str
    evidence_count: int
    evidence: tuple[RAGEvidenceRecord, ...]
    source_count: int
    document_count: int

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        _require_non_negative_int(self.evidence_count, "evidence_count")
        _require_non_negative_int(self.source_count, "source_count")
        _require_non_negative_int(self.document_count, "document_count")
        if not isinstance(self.evidence, tuple):
            raise ValueError("evidence must be a tuple of RAGEvidenceRecord instances.")
        if self.evidence_count != len(self.evidence):
            raise ValueError("evidence_count must match the evidence tuple length.")
        for item in self.evidence:
            if not isinstance(item, RAGEvidenceRecord):
                raise ValueError("evidence must contain RAGEvidenceRecord instances.")


def assemble_evidence(
    query_result: RAGQueryResult,
    max_evidence: int,
    minimum_similarity_score: float | None = None,
) -> EvidenceBundle:
    """Select deterministic traceable evidence from normalized RAG results."""

    normalized_query_result = _require_query_result(query_result)
    normalized_max_evidence = _require_positive_int(max_evidence, "max_evidence")
    normalized_minimum_similarity_score = _normalize_optional_score(minimum_similarity_score)

    try:
        selected = _select_evidence(
            normalized_query_result.results,
            normalized_query=normalized_query_result.query,
            max_evidence=normalized_max_evidence,
            minimum_similarity_score=normalized_minimum_similarity_score,
        )
        return _build_bundle(normalized_query_result.query, selected)
    except EvidenceAssemblyError:
        raise
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise EvidenceAssemblyConsistencyError("evidence assembly produced an invalid contract.") from exc


def _require_query_result(value: object) -> RAGQueryResult:
    if not isinstance(value, RAGQueryResult):
        raise EvidenceAssemblyInputError("query_result must be a RAGQueryResult instance.")
    if not isinstance(value.query, str) or not value.query.strip():
        raise EvidenceAssemblyInputError("query_result.query must be a non-empty string.")
    if not isinstance(value.results, tuple):
        raise EvidenceAssemblyConsistencyError("query_result.results must be an immutable tuple.")
    for item in value.results:
        if not isinstance(item, RAGResult):
            raise EvidenceAssemblyConsistencyError("query_result.results must contain RAGResult instances.")
    return value


def _select_evidence(
    results: tuple[RAGResult, ...],
    *,
    normalized_query: str,
    max_evidence: int,
    minimum_similarity_score: float | None,
) -> tuple[RAGEvidenceRecord, ...]:
    if not results:
        return ()

    selected: list[RAGEvidenceRecord] = []
    seen_result_signatures: dict[str, tuple[str, str, str, str, str, str, float | None, str | None, str | None]] = {}
    seen_ids: set[str] = set()

    for result in results:
        normalized_result = _normalize_rag_result(result)
        if minimum_similarity_score is not None:
            score = normalized_result.similarity_score
            if score is None or score < minimum_similarity_score:
                continue

        signature = _result_signature(normalized_result, normalized_query)
        previous_signature = seen_result_signatures.get(normalized_result.result_id)
        if previous_signature is not None:
            if previous_signature != signature:
                raise EvidenceAssemblyConsistencyError(
                    f"duplicate result_id {normalized_result.result_id!r} maps to contradictory evidence."
                )
            continue

        if normalized_result.result_id in seen_ids:
            raise EvidenceAssemblyConsistencyError(
                f"duplicate result_id {normalized_result.result_id!r} is inconsistent."
            )
        seen_ids.add(normalized_result.result_id)
        seen_result_signatures[normalized_result.result_id] = signature
        selected.append(
            RAGEvidenceRecord(
                result_id=normalized_result.result_id,
                query=normalized_query,
                company_name=normalized_result.company_name,
                source_id=normalized_result.source_id,
                document_id=normalized_result.document_id,
                chunk_id=normalized_result.chunk_id,
                text=normalized_result.text,
                similarity_score=normalized_result.similarity_score,
                retrieval_scope=normalized_result.retrieval_scope,
                source_url=normalized_result.source_url,
            )
        )
        if len(selected) >= max_evidence:
            break

    return tuple(selected)


def _build_bundle(query: str, evidence: tuple[RAGEvidenceRecord, ...]) -> EvidenceBundle:
    source_ids = {item.source_id for item in evidence if item.source_id.strip()}
    document_ids = {item.document_id for item in evidence if item.document_id.strip()}
    return EvidenceBundle(
        query=query,
        evidence_count=len(evidence),
        evidence=evidence,
        source_count=len(source_ids),
        document_count=len(document_ids),
    )


def _normalize_rag_result(result: RAGResult) -> RAGResult:
    if not isinstance(result, RAGResult):
        raise EvidenceAssemblyConsistencyError("query_result.results must contain RAGResult instances.")
    _require_text(result.result_id, "result_id")
    _require_text(result.company_name, "company_name")
    _require_text(result.document_id, "document_id")
    _require_text(result.chunk_id, "chunk_id")
    _require_text(result.source_id, "source_id")
    _require_text(result.text, "text")
    if result.similarity_score is not None:
        _require_numeric_finite(result.similarity_score, "similarity_score")
    if result.retrieval_scope is not None:
        _require_text(result.retrieval_scope, "retrieval_scope")
    if result.source_url is not None:
        _require_text(result.source_url, "source_url")
    return result


def _result_signature(
    result: RAGResult,
    query: str,
) -> tuple[str, str, str, str, str, str, str, float | None, str | None, str | None]:
    return (
        result.result_id,
        query,
        result.company_name,
        result.document_id,
        result.chunk_id,
        result.source_id,
        result.text,
        result.similarity_score,
        result.retrieval_scope,
        result.source_url,
    )


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceAssemblyInputError(f"{field_name} must be an integer.")
    if value <= 0:
        raise EvidenceAssemblyInputError(f"{field_name} must be positive.")
    return value


def _normalize_optional_score(value: float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceAssemblyInputError("minimum_similarity_score must be numeric when provided.")
    score = float(value)
    if not isfinite(score):
        raise EvidenceAssemblyInputError("minimum_similarity_score must be finite when provided.")
    return score


def _require_numeric_finite(value: float | int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceAssemblyConsistencyError(f"{field_name} must be numeric.")
    if not isfinite(float(value)):
        raise EvidenceAssemblyConsistencyError(f"{field_name} must be finite.")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be zero or positive.")
