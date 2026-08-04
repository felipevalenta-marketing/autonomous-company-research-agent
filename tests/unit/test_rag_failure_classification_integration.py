"""Focused integration test for the production RAG failure classification."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from starlette.testclient import TestClient

from app.api import _workflow_retrieval_failure, create_app
from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.graph.state import ResearchWorkflowError
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.utils.hashing import sha256_text
from app.rag.retrieval_service import RAGQueryError as RetrievalRAGQueryError
from app.models.providers import RAGResult
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceResult
from app.services.rag_query_service import query_company_rag
from app.services.vector_preparation_service import build_pinecone_namespace
from app.rag.retrieval_service import retrieve_rag_results
from app.graph.workflow import build_research_workflow
from app.services.workflow_integration_service import run_completed_workflow
from app.settings import Settings


class RecordingEmbeddingService:
    def __init__(self, result: EmbeddingServiceResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def __call__(self, query: str) -> EmbeddingServiceResult:
        self.calls.append(query)
        return self.result


class RecordingVectorQueryService:
    def __init__(self, result: PineconeQueryResponseDTO) -> None:
        self.result = result
        self.calls: list[tuple[tuple[float, ...], str, int, object]] = []

    def __call__(
        self,
        vector: tuple[float, ...],
        namespace: str,
        top_k: int,
        metadata_filter: object = None,
    ) -> PineconeQueryResponseDTO:
        self.calls.append((vector, namespace, top_k, metadata_filter))
        return self.result


class ResearchFailureClassificationIntegrationTests(unittest.TestCase):
    def _build_settings(self) -> Settings:
        return Settings(
            agent_api_key="secret",
            openai_api_key="demo",
            openai_base_url="https://api.openai.com/v1",
            openai_embedding_model="text-embedding-3-small",
            pinecone_api_key="demo",
            pinecone_index_name="index",
            pinecone_index_host="https://example.com",
            pinecone_namespace_prefix="company",
            pinecone_vector_dimension="3",
            pinecone_api_version=None,
            pinecone_max_upsert_batch_size="10",
            pinecone_max_query_top_k="5",
            tavily_api_key=None,
            news_api_key=None,
            alpha_vantage_api_key=None,
            sec_user_agent="Example App (dev@example.com)",
        )

    def _build_embedding_result(self, query: str) -> EmbeddingServiceResult:
        record = EmbeddingRecord(
            input_index=0,
            input_checksum="sha256-not-needed-for-test",
            model="text-embedding-3-small",
            vector_dimension=3,
            vector=(0.1, 0.2, 0.3),
        )
        return EmbeddingServiceResult(model="text-embedding-3-small", embeddings=(record,))

    def _build_match(self) -> PineconeQueryMatchDTO:
        return PineconeQueryMatchDTO(
            record_id="match-1",
            score=0.91,
            metadata={
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "source_id": "source-1",
                "text": "Relevant retrieved passage.",
                "source_url": "https://example.com/doc",
                "company_name": "Apple Inc.",
                "ticker": "AAPL",
                "cik": "0000320193",
                "content_checksum": "checksum-1",
            },
        )

    def _build_successful_query_result(self, query: str) -> PineconeQueryResponseDTO:
        company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")
        namespace = build_pinecone_namespace(company, "company")
        return PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace)

    def _build_rag_result(self, query: str) -> RAGResult:
        del query
        return RAGResult(
            result_id=sha256_text("source-1|doc-1|chunk-1|checksum-1"),
            company_name="Apple Inc.",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_id="source-1",
            text="Relevant retrieved passage.",
            similarity_score=0.91,
            retrieval_scope=build_pinecone_namespace(ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193"), "company"),
            source_url="https://example.com/doc",
        )

    def test_real_workflow_returns_failed_state_and_api_classifies_generic_rag_query_error(self) -> None:
        self.maxDiff = None
        query = "Analyze the company's recent financial performance and strategic risks"
        company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")
        runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")

        embedding_service = RecordingEmbeddingService(self._build_embedding_result(query))
        vector_query_service = RecordingVectorQueryService(self._build_successful_query_result(query))
        retrieval_namespace = build_pinecone_namespace(company, "company")
        trace: list[dict[str, object]] = []

        def traced_retrieve_rag_results(
            query_text: str,
            resolved_company: ResolvedCompany,
            embedding_boundary,
            vector_boundary,
            *,
            top_k: int,
            metadata_filter=None,
            namespace_prefix=None,
        ) -> tuple[RAGResult, ...]:
            trace.append(
                {
                    "boundary": "retrieve_rag_results",
                    "event": "enter",
                    "input_class": "tuple[RAGResult,...]",
                }
            )
            results = retrieve_rag_results(
                query_text,
                resolved_company,
                embedding_boundary,
                vector_boundary,
                top_k=top_k,
                metadata_filter=metadata_filter,
                namespace_prefix=namespace_prefix,
            )
            trace.append(
                {
                    "boundary": "retrieve_rag_results",
                    "event": "return",
                    "return_type": type(results).__name__,
                    "return_value": results,
                    "cause_type": None if getattr(results, "__cause__", None) is None else type(results.__cause__).__name__,
                    "context_type": None if getattr(results, "__context__", None) is None else type(results.__context__).__name__,
                }
            )
            trace.append(
                {
                    "boundary": "retrieve_rag_results",
                    "event": "raise",
                    "error_type": "RAGQueryError",
                    "cause_type": None,
                    "context_type": None,
                }
            )
            raise RetrievalRAGQueryError("RAG query orchestration failed.")

        def traced_query_company_rag(
            query_text: str,
            resolved_company: ResolvedCompany,
            embedding_boundary,
            vector_boundary,
            *,
            top_k: int,
            metadata_filter=None,
            namespace_prefix=None,
        ):
            trace.append(
                {
                    "boundary": "query_company_rag",
                    "event": "enter",
                    "input_class": "str",
                }
            )
            try:
                result = query_company_rag(
                    query_text,
                    resolved_company,
                    embedding_boundary,
                    vector_boundary,
                    top_k=top_k,
                    metadata_filter=metadata_filter,
                    namespace_prefix=namespace_prefix,
                    retrieval_service=traced_retrieve_rag_results,
                )
            except Exception as exc:
                trace.append(
                    {
                        "boundary": "query_company_rag",
                        "event": "raise",
                        "error_type": type(exc).__name__,
                        "cause_type": None if getattr(exc, "__cause__", None) is None else type(exc.__cause__).__name__,
                        "context_type": None if getattr(exc, "__context__", None) is None else type(exc.__context__).__name__,
                    }
                )
                raise
            trace.append(
                {
                    "boundary": "query_company_rag",
                    "event": "return",
                    "return_type": type(result).__name__,
                    "cause_type": None if getattr(result, "__cause__", None) is None else type(result.__cause__).__name__,
                    "context_type": None if getattr(result, "__context__", None) is None else type(result.__context__).__name__,
                }
            )
            return result

        def query_dependency(
            query_text: str,
            resolved_company: ResolvedCompany,
            embedding_boundary,
            vector_boundary,
            *,
            top_k: int,
            metadata_filter=None,
            namespace_prefix=None,
        ):
            trace.append(
                {
                    "boundary": "retrieve_research",
                    "event": "enter",
                    "state_keys": ("company_input", "research_query"),
                    "input_class": type(query_text).__name__,
                }
            )
            try:
                result = traced_query_company_rag(
                    query_text,
                    resolved_company,
                    embedding_boundary,
                    vector_boundary,
                    top_k=top_k,
                    metadata_filter=metadata_filter,
                    namespace_prefix=namespace_prefix,
                )
            except Exception as exc:
                trace.append(
                    {
                        "boundary": "retrieve_research",
                        "event": "raise",
                        "error_type": type(exc).__name__,
                        "cause_type": None if getattr(exc, "__cause__", None) is None else type(exc.__cause__).__name__,
                        "context_type": None if getattr(exc, "__context__", None) is None else type(exc.__context__).__name__,
                    }
                )
                raise
            trace.append(
                {
                    "boundary": "retrieve_research",
                    "event": "return",
                    "return_type": type(result).__name__,
                    "cause_type": None if getattr(result, "__cause__", None) is None else type(result.__cause__).__name__,
                    "context_type": None if getattr(result, "__context__", None) is None else type(result.__context__).__name__,
                }
            )
            return result

        workflow = build_research_workflow(
            company_resolution_dependency=lambda request, runtime, sec_client: company,  # noqa: ARG005
            runtime_config=runtime_config,
            sec_client=object(),
            embedding_service=embedding_service,
            vector_query_service=vector_query_service,
            rag_top_k=5,
            max_evidence=3,
            query_dependency=query_dependency,
            rag_namespace_prefix="company",
        )

        trace.append({"boundary": "workflow.invoke", "event": "enter"})
        final_state = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})
        trace.append(
            {
                "boundary": "workflow.invoke",
                "event": "return",
                "return_type": type(final_state).__name__,
                "state_type": type(final_state).__name__,
                "errors_type": type(final_state.get("errors")).__name__ if isinstance(final_state, dict) else None,
            }
        )
        invoke_trace = list(trace)
        trace.clear()

        self.assertIsInstance(final_state, dict)
        self.assertEqual(final_state["workflow_status"], "failed")
        self.assertEqual(final_state["current_stage"], "failed")
        self.assertIsInstance(final_state["errors"], tuple)
        self.assertEqual(len(final_state["errors"]), 1)

        error = final_state["errors"][0]
        self.assertIsInstance(error, ResearchWorkflowError)
        self.assertEqual(error.code, "RAGQueryError")
        self.assertEqual(error.message, "Research retrieval failed.")
        self.assertEqual(error.details, (("stage", "retrieving_research"), ("error_type", "RAGQueryError")))
        self.assertIsNone(getattr(error, "__cause__", None))
        self.assertIsNone(getattr(error, "__context__", None))

        self.assertEqual(embedding_service.calls, [query])
        self.assertEqual(len(vector_query_service.calls), 1)
        self.assertEqual(vector_query_service.calls[0][1], retrieval_namespace)

        self.assertEqual(_workflow_retrieval_failure(final_state), ("RAGQueryError", None))

        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=workflow,
                build_workflow_output=lambda state: self.fail("build_workflow_output must not run for a retrieval failure."),
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: None,
            ),
        )

        with TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": query,
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "RESEARCH_RETRIEVAL_FAILED",
                "message": "Research retrieval failed.",
            },
        )
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=workflow_execution error_type=RAGQueryError cause_type=None response_status=502",
        )
        self.assertEqual(
            invoke_trace,
            [
                {"boundary": "workflow.invoke", "event": "enter"},
                {"boundary": "retrieve_research", "event": "enter", "state_keys": ("company_input", "research_query"), "input_class": "str"},
                {"boundary": "query_company_rag", "event": "enter", "input_class": "str"},
                {"boundary": "retrieve_rag_results", "event": "enter", "input_class": "tuple[RAGResult,...]"},
                {
                    "boundary": "retrieve_rag_results",
                    "event": "return",
                    "return_type": "tuple",
                    "return_value": (self._build_rag_result(query),),
                    "cause_type": None,
                    "context_type": None,
                },
                {"boundary": "retrieve_rag_results", "event": "raise", "error_type": "RAGQueryError", "cause_type": None, "context_type": None},
                {"boundary": "query_company_rag", "event": "raise", "error_type": "RAGQueryError", "cause_type": None, "context_type": None},
                {"boundary": "retrieve_research", "event": "raise", "error_type": "RAGQueryError", "cause_type": None, "context_type": None},
                {"boundary": "workflow.invoke", "event": "return", "return_type": "dict", "state_type": "dict", "errors_type": "tuple"},
            ]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
