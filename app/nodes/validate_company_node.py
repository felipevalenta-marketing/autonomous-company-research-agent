"""Validation node for the research workflow foundation."""

from __future__ import annotations

from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.models.company import ResolvedCompany

_COMPANY_RESOLVED_STAGE = "company_resolved"
_FAILED_STAGE = "failed"


def build_validate_company_node():
    """Build the node that validates the resolved company before completion."""

    def validate_company(state: ResearchWorkflowState) -> ResearchWorkflowState:
        resolved_company = state.get("resolved_company")
        if not isinstance(resolved_company, ResolvedCompany) or not resolved_company.company_name.strip():
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_resolved_company",
                        message="Resolved company is missing or invalid.",
                        details=(("stage", "validate_company"),),
                    ),
                ),
            }

        return {
            "workflow_status": _COMPANY_RESOLVED_STAGE,
            "current_stage": _COMPANY_RESOLVED_STAGE,
        }

    return validate_company
