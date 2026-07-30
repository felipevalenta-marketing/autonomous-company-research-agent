"""Initialization node for the research workflow foundation."""

from __future__ import annotations

from app.graph.state import ResearchWorkflowError, ResearchWorkflowState

_FAILED_STAGE = "failed"
_INITIAL_STAGE = "initialized"


def build_initialize_research_node():
    """Build the deterministic initialization node."""

    def initialize_research(state: ResearchWorkflowState) -> ResearchWorkflowState:
        research_query = state.get("research_query")
        company_input = state.get("company_input")

        if not isinstance(research_query, str) or not research_query.strip():
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_research_query",
                        message="research_query must be a non-empty string.",
                    ),
                ),
            }

        if not isinstance(company_input, str) or not company_input.strip():
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_company_input",
                        message="company_input must be a non-empty string.",
                    ),
                ),
            }

        return {
            "research_query": research_query,
            "company_input": company_input,
            "workflow_status": _INITIAL_STAGE,
            "current_stage": _INITIAL_STAGE,
            "errors": (),
        }

    return initialize_research
