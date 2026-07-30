"""LangGraph workflow foundation for company research and retrieval."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from langgraph.graph import END, START, StateGraph

from app.clients.pinecone_dtos import PineconeQueryResponseDTO
from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.nodes.assemble_evidence_node import EvidenceAssemblyDependency, build_assemble_evidence_node
from app.nodes.initialize_research_node import build_initialize_research_node
from app.nodes.resolve_company_node import CompanyResolutionDependency, build_resolve_company_node
from app.nodes.retrieve_research_node import RAGQueryDependency, build_retrieve_research_node
from app.nodes.validate_company_node import build_validate_company_node
from app.services.company_resolution_service import SecTickerClientProtocol
from app.services.embedding_service import EmbeddingServiceResult
from app.services.evidence_assembly_service import EvidenceBundle, assemble_evidence
from app.services.rag_query_service import RAGQueryResult, query_company_rag

_RESOLVING_STAGE = "resolving_company"
_COMPANY_RESOLVED_STAGE = "company_resolved"
_RETRIEVING_STAGE = "retrieving_research"
_RESEARCH_RETRIEVED_STAGE = "research_retrieved"
_ASSEMBLING_STAGE = "assembling_evidence"
_EVIDENCE_ASSEMBLED_STAGE = "evidence_assembled"
_COMPLETED_STAGE = "completed"
_FAILED_STAGE = "failed"


def _route_after_initialization(state: ResearchWorkflowState) -> str:
    return "fail_workflow" if state.get("workflow_status") == _FAILED_STAGE else "resolve_company"


def _route_after_resolution(state: ResearchWorkflowState) -> str:
    return "fail_workflow" if state.get("workflow_status") == _FAILED_STAGE else "validate_company"


def _route_after_validation(state: ResearchWorkflowState) -> str:
    return "retrieve_research" if state.get("workflow_status") == _COMPANY_RESOLVED_STAGE else "fail_workflow"


def _route_after_retrieval(state: ResearchWorkflowState) -> str:
    return "assemble_evidence" if state.get("workflow_status") == _RESEARCH_RETRIEVED_STAGE else "fail_workflow"


def _route_after_evidence(state: ResearchWorkflowState) -> str:
    return "complete_workflow" if state.get("workflow_status") == _EVIDENCE_ASSEMBLED_STAGE else "fail_workflow"


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
        rag_query_result = state.get("rag_query_result")
        if isinstance(rag_query_result, RAGQueryResult):
            result["rag_query_result"] = rag_query_result
        evidence_bundle = state.get("evidence_bundle")
        if isinstance(evidence_bundle, EvidenceBundle):
            result["evidence_bundle"] = evidence_bundle
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
        rag_query_result = state.get("rag_query_result")
        if isinstance(rag_query_result, RAGQueryResult):
            result["rag_query_result"] = rag_query_result
        evidence_bundle = state.get("evidence_bundle")
        if isinstance(evidence_bundle, EvidenceBundle):
            result["evidence_bundle"] = evidence_bundle
        return result

    return fail_workflow


def build_research_workflow(
    *,
    company_resolution_dependency: CompanyResolutionDependency,
    runtime_config: RuntimeConfig,
    sec_client: SecTickerClientProtocol,
    embedding_service: Callable[[str], EmbeddingServiceResult],
    vector_query_service: Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
    rag_top_k: int,
    max_evidence: int,
    query_dependency: RAGQueryDependency = query_company_rag,
    rag_metadata_filter: Mapping[str, object] | None = None,
    rag_namespace_prefix: str | None = None,
    assemble_evidence_dependency: EvidenceAssemblyDependency = assemble_evidence,
    minimum_similarity_score: float | None = None,
):
    """Build and compile the minimal company-research workflow."""

    builder: StateGraph[ResearchWorkflowState] = StateGraph(ResearchWorkflowState)
    builder.add_node("initialize_research", build_initialize_research_node())
    builder.add_node(
        "resolve_company",
        build_resolve_company_node(company_resolution_dependency, runtime_config, sec_client),
    )
    builder.add_node("validate_company", build_validate_company_node())
    builder.add_node(
        "retrieve_research",
        build_retrieve_research_node(
            query_dependency,
            embedding_service=embedding_service,
            vector_query_service=vector_query_service,
            top_k=rag_top_k,
            metadata_filter=rag_metadata_filter,
            namespace_prefix=rag_namespace_prefix,
        ),
    )
    builder.add_node(
        "assemble_evidence",
        build_assemble_evidence_node(
            assemble_evidence_dependency,
            max_evidence=max_evidence,
            minimum_similarity_score=minimum_similarity_score,
        ),
    )
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
            "retrieve_research": "retrieve_research",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_conditional_edges(
        "retrieve_research",
        _route_after_retrieval,
        {
            "assemble_evidence": "assemble_evidence",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_conditional_edges(
        "assemble_evidence",
        _route_after_evidence,
        {
            "complete_workflow": "complete_workflow",
            "fail_workflow": "fail_workflow",
        },
    )
    builder.add_edge("complete_workflow", END)
    builder.add_edge("fail_workflow", END)

    return builder.compile()
