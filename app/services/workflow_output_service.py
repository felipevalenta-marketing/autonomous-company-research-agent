"""Deterministic workflow output packaging for completed research runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle


class WorkflowOutputError(Exception):
    """Base exception for workflow output packaging failures."""


class WorkflowOutputInputError(WorkflowOutputError):
    """Raised when workflow output inputs are invalid."""


class WorkflowOutputConsistencyError(WorkflowOutputError):
    """Raised when completed workflow state is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class WorkflowOutput:
    """Immutable final workflow artifact bundle."""

    research_query: str
    resolved_company: ResolvedCompany
    evidence_bundle: EvidenceBundle

    def __post_init__(self) -> None:
        _require_text(self.research_query, "research_query")
        if not isinstance(self.resolved_company, ResolvedCompany):
            raise ValueError("resolved_company must be a ResolvedCompany instance.")
        if not isinstance(self.evidence_bundle, EvidenceBundle):
            raise ValueError("evidence_bundle must be an EvidenceBundle instance.")


def build_workflow_output(workflow_state: Mapping[str, object]) -> WorkflowOutput:
    """Validate a completed workflow state and package the final artifacts."""

    normalized_state = _require_workflow_state(workflow_state)
    _require_completed_state(normalized_state)

    research_query = _require_text(normalized_state.get("research_query"), "research_query")
    resolved_company = _require_resolved_company(normalized_state.get("resolved_company"))
    evidence_bundle = _require_evidence_bundle(normalized_state.get("evidence_bundle"))
    _require_artifact_alignment(research_query, evidence_bundle)

    return WorkflowOutput(
        research_query=research_query,
        resolved_company=resolved_company,
        evidence_bundle=evidence_bundle,
    )


def _require_workflow_state(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowOutputInputError("workflow_state must be a mapping.")
    return value


def _require_completed_state(state: Mapping[str, object]) -> None:
    workflow_status = state.get("workflow_status")
    current_stage = state.get("current_stage")
    if workflow_status != "completed" or current_stage != "completed":
        raise WorkflowOutputInputError("workflow_state must represent a completed workflow.")


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowOutputConsistencyError(f"{field_name} must be a non-empty string.")
    return value


def _require_resolved_company(value: object) -> ResolvedCompany:
    if not isinstance(value, ResolvedCompany):
        raise WorkflowOutputConsistencyError("resolved_company must be a ResolvedCompany instance.")
    return value


def _require_evidence_bundle(value: object) -> EvidenceBundle:
    if not isinstance(value, EvidenceBundle):
        raise WorkflowOutputConsistencyError("evidence_bundle must be an EvidenceBundle instance.")
    return value


def _require_artifact_alignment(research_query: str, evidence_bundle: EvidenceBundle) -> None:
    if evidence_bundle.query != research_query:
        raise WorkflowOutputConsistencyError("evidence_bundle.query must match research_query.")
    if evidence_bundle.evidence_count != len(evidence_bundle.evidence):
        raise WorkflowOutputConsistencyError("evidence_bundle.evidence_count must match evidence length.")
