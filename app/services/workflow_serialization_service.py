"""Deterministic serialization for completed workflow outputs."""

from __future__ import annotations

from math import isfinite

from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_output_service import WorkflowOutput


class WorkflowSerializationError(Exception):
    """Base exception for workflow serialization failures."""


class WorkflowSerializationInputError(WorkflowSerializationError):
    """Raised when workflow serialization inputs are invalid."""


class WorkflowSerializationConsistencyError(WorkflowSerializationError):
    """Raised when workflow output artifacts are malformed or inconsistent."""


def serialize_workflow_output(workflow_output: WorkflowOutput) -> dict[str, object]:
    """Serialize a completed workflow output into a JSON-compatible payload."""

    normalized_output = _require_workflow_output(workflow_output)
    _require_artifact_alignment(normalized_output.research_query, normalized_output.evidence_bundle)
    return {
        "research_query": normalized_output.research_query,
        "resolved_company": _serialize_resolved_company(normalized_output.resolved_company),
        "evidence_bundle": _serialize_evidence_bundle(normalized_output.evidence_bundle),
    }


def _require_workflow_output(value: object) -> WorkflowOutput:
    if not isinstance(value, WorkflowOutput):
        raise WorkflowSerializationInputError("workflow_output must be a WorkflowOutput instance.")
    _require_text(value.research_query, "research_query")
    _require_resolved_company(value.resolved_company)
    _require_evidence_bundle(value.evidence_bundle)
    return value


def _require_resolved_company(value: object) -> ResolvedCompany:
    if not isinstance(value, ResolvedCompany):
        raise WorkflowSerializationConsistencyError("resolved_company must be a ResolvedCompany instance.")
    _require_text(value.company_name, "resolved_company.company_name")
    for field_name in ("ticker", "cik", "exchange", "country", "security_type", "company_id", "website_url"):
        field_value = getattr(value, field_name)
        if field_value is not None and not isinstance(field_value, str):
            raise WorkflowSerializationConsistencyError(f"resolved_company.{field_name} must be a string or null.")
    return value


def _require_evidence_bundle(value: object) -> EvidenceBundle:
    if not isinstance(value, EvidenceBundle):
        raise WorkflowSerializationConsistencyError("evidence_bundle must be an EvidenceBundle instance.")
    _require_text(value.query, "evidence_bundle.query")
    _require_non_negative_int(value.evidence_count, "evidence_bundle.evidence_count")
    _require_non_negative_int(value.source_count, "evidence_bundle.source_count")
    _require_non_negative_int(value.document_count, "evidence_bundle.document_count")
    if not isinstance(value.evidence, tuple):
        raise WorkflowSerializationConsistencyError("evidence_bundle.evidence must be an immutable tuple.")
    if value.evidence_count != len(value.evidence):
        raise WorkflowSerializationConsistencyError("evidence_bundle.evidence_count must match evidence length.")
    for item in value.evidence:
        _require_evidence_record(item)
    return value


def _require_artifact_alignment(research_query: str, evidence_bundle: EvidenceBundle) -> None:
    if evidence_bundle.query != research_query:
        raise WorkflowSerializationConsistencyError("evidence_bundle.query must match research_query.")


def _require_evidence_record(value: object) -> RAGEvidenceRecord:
    if not isinstance(value, RAGEvidenceRecord):
        raise WorkflowSerializationConsistencyError("evidence_bundle.evidence must contain RAGEvidenceRecord instances.")
    _require_text(value.result_id, "evidence_bundle.evidence.result_id")
    _require_text(value.query, "evidence_bundle.evidence.query")
    _require_text(value.company_name, "evidence_bundle.evidence.company_name")
    _require_text(value.source_id, "evidence_bundle.evidence.source_id")
    _require_text(value.document_id, "evidence_bundle.evidence.document_id")
    _require_text(value.chunk_id, "evidence_bundle.evidence.chunk_id")
    _require_text(value.text, "evidence_bundle.evidence.text")
    if value.similarity_score is not None:
        _require_numeric_finite(value.similarity_score, "evidence_bundle.evidence.similarity_score")
    if value.retrieval_scope is not None:
        _require_text(value.retrieval_scope, "evidence_bundle.evidence.retrieval_scope")
    if value.source_url is not None:
        _require_text(value.source_url, "evidence_bundle.evidence.source_url")
    return value


def _serialize_resolved_company(resolved_company: ResolvedCompany) -> dict[str, object]:
    return {
        "company_name": resolved_company.company_name,
        "ticker": resolved_company.ticker,
        "cik": resolved_company.cik,
        "exchange": resolved_company.exchange,
        "country": resolved_company.country,
        "security_type": resolved_company.security_type,
        "company_id": resolved_company.company_id,
        "website_url": resolved_company.website_url,
    }


def _serialize_evidence_bundle(evidence_bundle: EvidenceBundle) -> dict[str, object]:
    return {
        "query": evidence_bundle.query,
        "evidence_count": evidence_bundle.evidence_count,
        "evidence": [_serialize_evidence_record(item) for item in evidence_bundle.evidence],
        "source_count": evidence_bundle.source_count,
        "document_count": evidence_bundle.document_count,
    }


def _serialize_evidence_record(evidence_record: RAGEvidenceRecord) -> dict[str, object]:
    return {
        "result_id": evidence_record.result_id,
        "query": evidence_record.query,
        "company_name": evidence_record.company_name,
        "source_id": evidence_record.source_id,
        "document_id": evidence_record.document_id,
        "chunk_id": evidence_record.chunk_id,
        "text": evidence_record.text,
        "similarity_score": evidence_record.similarity_score,
        "retrieval_scope": evidence_record.retrieval_scope,
        "source_url": evidence_record.source_url,
    }


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowSerializationConsistencyError(f"{field_name} must be a non-empty string.")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkflowSerializationConsistencyError(f"{field_name} must be an integer.")
    if value < 0:
        raise WorkflowSerializationConsistencyError(f"{field_name} must be zero or positive.")


def _require_numeric_finite(value: float | int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowSerializationConsistencyError(f"{field_name} must be numeric.")
    if not isfinite(float(value)):
        raise WorkflowSerializationConsistencyError(f"{field_name} must be finite.")
