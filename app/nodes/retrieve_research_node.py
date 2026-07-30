"""Research retrieval node for the LangGraph workflow foundation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from app.clients.pinecone_dtos import PineconeQueryResponseDTO
from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.models.company import ResolvedCompany
from app.services.embedding_service import EmbeddingServiceResult
from app.services.rag_query_service import RAGQueryError, RAGQueryResult
from app.rag.retrieval_service import RAGEmbeddingError, RAGRetrievalError

RAGQueryDependency = Callable[
    [
        str,
        ResolvedCompany,
        Callable[[str], EmbeddingServiceResult],
        Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
    ],
    RAGQueryResult,
]

_RETRIEVING_STAGE = "retrieving_research"
_RESEARCH_RETRIEVED_STAGE = "research_retrieved"
_FAILED_STAGE = "failed"


def build_retrieve_research_node(
    query_dependency: RAGQueryDependency,
    *,
    embedding_service: Callable[[str], EmbeddingServiceResult],
    vector_query_service: Callable[[Sequence[float], str, int, Mapping[str, object] | None], PineconeQueryResponseDTO],
    top_k: int,
    metadata_filter: Mapping[str, object] | None = None,
    namespace_prefix: str | None = None,
):
    """Build the deterministic research retrieval node."""

    def retrieve_research(state: ResearchWorkflowState) -> ResearchWorkflowState:
        research_query = state.get("research_query")
        resolved_company = state.get("resolved_company")
        if not isinstance(research_query, str) or not research_query.strip():
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_retrieval_state",
                        message="research_query must be a non-empty string before retrieval.",
                        details=(("stage", _RETRIEVING_STAGE),),
                    ),
                ),
            }
        if not isinstance(resolved_company, ResolvedCompany):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_retrieval_state",
                        message="resolved_company must be a canonical ResolvedCompany before retrieval.",
                        details=(("stage", _RETRIEVING_STAGE),),
                    ),
                ),
            }

        try:
            rag_query_result = query_dependency(
                research_query,
                resolved_company,
                embedding_service,
                vector_query_service,
                top_k=top_k,
                metadata_filter=metadata_filter,
                namespace_prefix=namespace_prefix,
            )
        except (RAGQueryError, RAGEmbeddingError, RAGRetrievalError) as exc:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code=exc.__class__.__name__,
                        message="Research retrieval failed.",
                        details=(("stage", _RETRIEVING_STAGE),),
                    ),
                ),
            }
        except Exception as exc:  # pragma: no cover - defensive workflow boundary
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="research_retrieval_failure",
                        message="Research retrieval failed.",
                        details=(
                            ("stage", _RETRIEVING_STAGE),
                            ("error_type", exc.__class__.__name__),
                        ),
                    ),
                ),
            }

        if not isinstance(rag_query_result, RAGQueryResult):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_rag_query_output",
                        message="Research retrieval returned an invalid RAGQueryResult.",
                        details=(("stage", _RETRIEVING_STAGE),),
                    ),
                ),
            }
        if rag_query_result.query != research_query:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="malformed_rag_query_output",
                        message="Research retrieval returned a query that does not match the workflow request.",
                        details=(("stage", _RETRIEVING_STAGE),),
                    ),
                ),
            }

        return {
            "rag_query_result": rag_query_result,
            "workflow_status": _RESEARCH_RETRIEVED_STAGE,
            "current_stage": _RESEARCH_RETRIEVED_STAGE,
            "errors": (),
        }

    return retrieve_research
