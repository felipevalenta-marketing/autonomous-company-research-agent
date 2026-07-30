"""LangGraph workflow foundation for company research."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.nodes.initialize_research_node import build_initialize_research_node
from app.nodes.resolve_company_node import CompanyResolutionDependency, build_resolve_company_node
from app.nodes.validate_company_node import build_validate_company_node
from app.services.company_resolution_service import SecTickerClientProtocol

_RESOLVING_STAGE = "resolving_company"
_COMPANY_RESOLVED_STAGE = "company_resolved"
_COMPLETED_STAGE = "completed"
_FAILED_STAGE = "failed"


def _route_after_initialization(state: ResearchWorkflowState) -> str:
    return "fail_workflow" if state.get("workflow_status") == _FAILED_STAGE else "resolve_company"


def _route_after_resolution(state: ResearchWorkflowState) -> str:
    return "fail_workflow" if state.get("workflow_status") == _FAILED_STAGE else "validate_company"


def _route_after_validation(state: ResearchWorkflowState) -> str:
    return "complete_workflow" if state.get("workflow_status") == _COMPANY_RESOLVED_STAGE else "fail_workflow"


def _build_complete_workflow_node():
    def complete_workflow(state: ResearchWorkflowState) -> ResearchWorkflowState:
        result: ResearchWorkflowState = {
            "workflow_status": _COMPLETED_STAGE,
            "current_stage": _COMPLETED_STAGE,
            "errors": (),
        }
        research_query = state.get("research_query")
        if isinstance(research_query, str):
            result["research_query"] = research_query
        company_input = state.get("company_input")
        if isinstance(company_input, str):
            result["company_input"] = company_input
        resolved_company = state.get("resolved_company")
        if isinstance(resolved_company, ResolvedCompany):
            result["resolved_company"] = resolved_company
        return result

    return complete_workflow


def _build_fail_workflow_node():
    def fail_workflow(state: ResearchWorkflowState) -> ResearchWorkflowState:
        errors = state.get("errors", ())
        if not errors:
            errors = (
                ResearchWorkflowError(
                    code="workflow_failed",
                    message="The research workflow failed before completion.",
                ),
            )

        result: ResearchWorkflowState = {
            "workflow_status": _FAILED_STAGE,
            "current_stage": _FAILED_STAGE,
            "errors": errors,
        }
        research_query = state.get("research_query")
        if isinstance(research_query, str):
            result["research_query"] = research_query
        company_input = state.get("company_input")
        if isinstance(company_input, str):
            result["company_input"] = company_input

        resolved_company = state.get("resolved_company")
        if isinstance(resolved_company, ResolvedCompany):
            result["resolved_company"] = resolved_company

        return result

    return fail_workflow


def build_research_workflow(
    *,
    company_resolution_dependency: CompanyResolutionDependency,
    runtime_config: RuntimeConfig,
    sec_client: SecTickerClientProtocol,
):
    """Build and compile the minimal company-research workflow."""

    builder: StateGraph[ResearchWorkflowState] = StateGraph(ResearchWorkflowState)
    builder.add_node("initialize_research", build_initialize_research_node())
    builder.add_node(
        "resolve_company",
        build_resolve_company_node(company_resolution_dependency, runtime_config, sec_client),
    )
    builder.add_node("validate_company", build_validate_company_node())
    builder.add_node("complete_workflow", _build_complete_workflow_node())
    builder.add_node("fail_workflow", _build_fail_workflow_node())

    builder.add_edge(START, "initialize_research")
    builder.add_conditional_edges(
        "initialize_research",
        _route_after_initialization,
        {
            "resolve_company": "resolve_company",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_conditional_edges(
        "resolve_company",
        _route_after_resolution,
        {
            "validate_company": "validate_company",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_conditional_edges(
        "validate_company",
        _route_after_validation,
        {
            "complete_workflow": "complete_workflow",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_edge("complete_workflow", END)
    builder.add_edge("fail_workflow", END)

    return builder.compile()
