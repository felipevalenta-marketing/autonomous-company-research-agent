"""Evidence assembly node for the LangGraph workflow foundation."""

from __future__ import annotations

from collections.abc import Callable

from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.services.evidence_assembly_service import EvidenceAssemblyError, EvidenceBundle
from app.services.rag_query_service import RAGQueryResult

EvidenceAssemblyDependency = Callable[[RAGQueryResult, int, float | None], EvidenceBundle]

_ASSEMBLING_STAGE = "assembling_evidence"
_EVIDENCE_ASSEMBLED_STAGE = "evidence_assembled"
_FAILED_STAGE = "failed"


def build_assemble_evidence_node(
    assembly_dependency: EvidenceAssemblyDependency,
    *,
    max_evidence: int,
    minimum_similarity_score: float | None = None,
):
    """Build the deterministic evidence assembly node."""

    def assemble_evidence(state: ResearchWorkflowState) -> ResearchWorkflowState:
        rag_query_result = state.get("rag_query_result")
        research_query = state.get("research_query")
        if not isinstance(rag_query_result, RAGQueryResult):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_evidence_state",
                        message="rag_query_result must be present before evidence assembly.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }
        if not isinstance(research_query, str) or rag_query_result.query != research_query:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_evidence_input",
                        message="rag_query_result.query must match the workflow research query.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }

        try:
            evidence_bundle = assembly_dependency(
                rag_query_result,
                max_evidence,
                minimum_similarity_score,
            )
        except EvidenceAssemblyError as exc:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code=exc.__class__.__name__,
                        message="Evidence assembly failed.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }
        except Exception as exc:  # pragma: no cover - defensive workflow boundary
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="evidence_assembly_failure",
                        message="Evidence assembly failed.",
                        details=(
                            ("stage", _ASSEMBLING_STAGE),
                            ("error_type", exc.__class__.__name__),
                        ),
                    ),
                ),
            }

        if not isinstance(evidence_bundle, EvidenceBundle):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_evidence_output",
                        message="Evidence assembly returned an invalid EvidenceBundle.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }
        if evidence_bundle.query != research_query:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_evidence_output",
                        message="Evidence assembly returned a bundle for a different query.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }
        if evidence_bundle.evidence_count != len(evidence_bundle.evidence):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_evidence_output",
                        message="Evidence assembly returned an inconsistent evidence count.",
                        details=(("stage", _ASSEMBLING_STAGE),),
                    ),
                ),
            }

        return {
            "evidence_bundle": evidence_bundle,
            "workflow_status": _EVIDENCE_ASSEMBLED_STAGE,
            "current_stage": _EVIDENCE_ASSEMBLED_STAGE,
            "errors": (),
        }

    return assemble_evidence
