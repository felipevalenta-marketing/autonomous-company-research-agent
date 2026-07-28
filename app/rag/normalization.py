
"""Canonical RAG normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.models.company import ResolvedCompany
from app.models.providers import RAGResult
from app.utils.hashing import sha256_text


class RAGNormalizationError(Exception):
    """Base exception for RAG normalization failures."""


class RAGMetadataError(RAGNormalizationError):
    """Raised when Pinecone metadata cannot be normalized into a RAG result."""


class RAGScoreError(RAGNormalizationError):
    """Raised when a match score is invalid."""


@dataclass(frozen=True, slots=True)
class _NormalizedCandidate:
    result: RAGResult
    tie_key: tuple[str, str, str, str, str, str]


def normalize_rag_results(
    resolved_company: ResolvedCompany,
    response: PineconeQueryResponseDTO,
    *,
    retrieval_scope: str | None = None,
) -> tuple[RAGResult, ...]:
    """Convert validated Pinecone matches into canonical RAG results."""

    if not isinstance(resolved_company, ResolvedCompany):
        raise RAGNormalizationError("resolved_company must be a ResolvedCompany instance.")
    if not isinstance(response, PineconeQueryResponseDTO):
        raise RAGNormalizationError("response must be a PineconeQueryResponseDTO instance.")

    scope = _normalize_optional_text(retrieval_scope) or _normalize_optional_text(response.namespace)
    candidates: list[_NormalizedCandidate] = []
    for match in response.matches:
        candidate = _normalize_match(resolved_company, match, scope)
        if candidate is not None:
            candidates.append(candidate)

    deduplicated: dict[str, _NormalizedCandidate] = {}
    for candidate in candidates:
        current = deduplicated.get(candidate.result.result_id)
        if current is None:
            deduplicated[candidate.result.result_id] = candidate
            continue
        if candidate.result.similarity_score > current.result.similarity_score:
            deduplicated[candidate.result.result_id] = candidate
            continue
        if candidate.result.similarity_score == current.result.similarity_score and candidate.tie_key < current.tie_key:
            deduplicated[candidate.result.result_id] = candidate

    ordered = sorted(
        deduplicated.values(),
        key=lambda candidate: (-candidate.result.similarity_score, candidate.result.result_id),
    )
    return tuple(candidate.result for candidate in ordered)


def _normalize_match(
    resolved_company: ResolvedCompany,
    match: PineconeQueryMatchDTO,
    retrieval_scope: str | None,
) -> _NormalizedCandidate | None:
    if not isinstance(match, PineconeQueryMatchDTO):
        raise RAGNormalizationError("response must contain PineconeQueryMatchDTO instances.")

    score = _normalize_score(match.score)
    metadata = _normalize_metadata(match.metadata)
    _validate_company_identity(resolved_company, metadata)

    source_id = _required_identifier(metadata.get("source_id"), "source_id")
    document_id = _required_identifier(metadata.get("document_id"), "document_id")
    chunk_id = _required_identifier(metadata.get("chunk_id"), "chunk_id")
    text = _extract_text(metadata)
    if source_id is None or document_id is None or chunk_id is None or text is None:
        return None

    source_url = _optional_identifier(metadata.get("source_url"), "source_url")
    result_id = _build_result_id(source_id, document_id, chunk_id, metadata, text)
    result = RAGResult(
        result_id=result_id,
        company_name=resolved_company.company_name.strip(),
        document_id=document_id,
        chunk_id=chunk_id,
        source_id=source_id,
        text=text,
        similarity_score=score,
        retrieval_scope=retrieval_scope,
        source_url=source_url,
    )
    checksum_value = metadata.get("content_checksum")
    if not isinstance(checksum_value, str) or not checksum_value.strip():
        checksum_value = sha256_text(text)
    tie_key = (
        document_id,
        chunk_id,
        source_id,
        source_url or "",
        checksum_value.strip(),
        match.record_id,
    )
    return _NormalizedCandidate(result=result, tie_key=tie_key)


def _build_result_id(
    source_id: str,
    document_id: str,
    chunk_id: str,
    metadata: Mapping[str, object],
    text: str,
) -> str:
    content_checksum = metadata.get("content_checksum")
    if isinstance(content_checksum, str) and content_checksum.strip():
        checksum = content_checksum.strip()
    else:
        checksum = sha256_text(text)
    return sha256_text(f"{source_id}|{document_id}|{chunk_id}|{checksum}")


def _normalize_metadata(metadata: object) -> dict[str, object]:
    if not isinstance(metadata, Mapping):
        raise RAGMetadataError("match metadata must be a mapping.")
    normalized: dict[str, object] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip():
            raise RAGMetadataError("metadata keys must be non-empty strings.")
        normalized_key = key.strip()
        if value is None:
            normalized[normalized_key] = None
            continue
        if isinstance(value, Mapping):
            raise RAGMetadataError("metadata values must be simple JSON-compatible values.")
        if isinstance(value, (list, tuple)):
            raise RAGMetadataError("metadata lists are not supported in RAG normalization.")
        if isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        if isinstance(value, int):
            normalized[normalized_key] = value
            continue
        if isinstance(value, float):
            if not isfinite(value):
                raise RAGScoreError("metadata numeric values must be finite.")
            normalized[normalized_key] = value
            continue
        if isinstance(value, str):
            normalized[normalized_key] = value.strip()
            continue
        raise RAGMetadataError("metadata values must be JSON-compatible scalars.")
    return normalized


def _validate_company_identity(resolved_company: ResolvedCompany, metadata: Mapping[str, object]) -> None:
    expected_company_name = _normalize_company_name(resolved_company.company_name)
    actual_company_name = _optional_identifier(metadata.get("company_name"), "company_name")
    if actual_company_name is not None and _normalize_company_name(actual_company_name) != expected_company_name:
        raise RAGMetadataError("match company_name metadata did not match the resolved company.")

    expected_ticker = _normalize_ticker(resolved_company.ticker)
    actual_ticker = _optional_identifier(metadata.get("ticker"), "ticker")
    if expected_ticker is not None and actual_ticker is not None and _normalize_ticker(actual_ticker) != expected_ticker:
        raise RAGMetadataError("match ticker metadata did not match the resolved company.")

    expected_cik = _normalize_cik(resolved_company.cik)
    actual_cik = _optional_identifier(metadata.get("cik"), "cik")
    if expected_cik is not None and actual_cik is not None and _normalize_cik(actual_cik) != expected_cik:
        raise RAGMetadataError("match cik metadata did not match the resolved company.")


def _extract_text(metadata: Mapping[str, object]) -> str | None:
    for key in ("text", "content"):
        value = metadata.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise RAGMetadataError(f"{key} metadata must be a string when provided.")
        stripped = value.strip()
        if not stripped:
            return None
        return stripped
    return None


def _normalize_score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RAGScoreError("similarity scores must be numeric.")
    score = float(value)
    if not isfinite(score):
        raise RAGScoreError("similarity scores must be finite.")
    return score


def _required_identifier(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RAGMetadataError(f"{field_name} metadata must be a string when provided.")
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _optional_identifier(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RAGMetadataError(f"{field_name} metadata must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_company_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _normalize_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).casefold()


def _normalize_cik(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.isdigit():
        raise RAGMetadataError("cik metadata must contain only digits.")
    stripped = normalized.lstrip("0")
    return stripped or "0"
