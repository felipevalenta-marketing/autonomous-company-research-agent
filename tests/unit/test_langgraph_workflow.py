"""Unit tests for the LangGraph workflow foundation."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.providers import RAGResult
from app.models.request import ResearchRequest
from app.services.company_resolution_service import CompanyResolutionNoMatchError
from app.services.evidence_assembly_service import (
    EvidenceAssemblyInputError,
    EvidenceBundle,
    RAGEvidenceRecord,
)
from app.services.rag_query_service import RAGQueryError, RAGQueryInputError, RAGQueryResult
from app.rag.retrieval_service import (
    RAGEmbeddingError,
    RAGQueryNamespaceConsistencyError,
    RAGQueryResponseConsistencyError,
)
from app.clients.openai_embeddings_client import OpenAIEmbeddingsTransportError


class FakeSecClient:
    """In-memory SEC client placeholder for offline workflow tests."""

    pass


class RecordingCompanyResolver:
    """Resolver fake that records every call."""

    def __init__(self, result: ResolvedCompany | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[ResearchRequest, RuntimeConfig, FakeSecClient]] = []

    def __call__(
        self,
        request: ResearchRequest,
        runtime_config: RuntimeConfig,
        sec_client: FakeSecClient,
    ) -> ResolvedCompany:
        self.calls.append((request, runtime_config, sec_client))
        if self.error is not None:
            raise self.error
        if self.result is None:
            return ResolvedCompany(company_name=request.company_name or "Example Corp", ticker="EXM", cik="0000000001")
        return self.result


class RecordingRAGQueryDependency:
    """Fake retrieval boundary that records every call."""

    def __init__(self, result: RAGQueryResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def __call__(
        self,
        query: str,
        resolved_company: ResolvedCompany,
        embedding_service,
        vector_query_service,
        *,
        top_k: int,
        metadata_filter=None,
        namespace_prefix=None,
    ) -> RAGQueryResult:
        self.calls.append(
            (
                query,
                resolved_company,
                embedding_service,
                vector_query_service,
                top_k,
                metadata_filter,
                namespace_prefix,
            )
        )
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("fake RAG query dependency was not configured.")
        return self.result


class RecordingEvidenceAssemblyDependency:
    """Fake evidence-assembly boundary that records every call."""

    def __init__(self, result: EvidenceBundle | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def __call__(
        self,
        query_result: RAGQueryResult,
        max_evidence: int,
        minimum_similarity_score: float | None = None,
    ) -> EvidenceBundle:
        self.calls.append((query_result, max_evidence, minimum_similarity_score))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("fake evidence assembly dependency was not configured.")
        return self.result


class LangGraphWorkflowTests(unittest.TestCase):
    """Focused tests for the workflow foundation."""

    def setUp(self) -> None:
        self.runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")
        self.sec_client = FakeSecClient()
        self.resolved_company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")
        self.embedding_service = object()
        self.vector_query_service = object()
        self.metadata_filter = {"source_id": "source-1"}
        self.namespace_prefix = "company"

    def tearDown(self) -> None:
        for module_name in tuple(sys.modules):
            if module_name.startswith("langgraph") or module_name.startswith("langchain_core"):
                sys.modules.pop(module_name, None)

    def _build_rag_result(self, query: str, *, result_id: str = "result-1") -> RAGResult:
        return RAGResult(
            result_id=result_id,
            company_name="Apple Inc.",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_id="source-1",
            text="Relevant retrieved passage.",
            similarity_score=0.92,
            retrieval_scope="company:cik:0000320193",
            source_url="https://example.com/doc",
        )

    def _build_evidence_record(self, query: str, *, result_id: str = "result-1") -> RAGEvidenceRecord:
        return RAGEvidenceRecord(
            result_id=result_id,
            query=query,
            company_name="Apple Inc.",
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-1",
            text="Relevant retrieved passage.",
            similarity_score=0.92,
            retrieval_scope="company:cik:0000320193",
            source_url="https://example.com/doc",
        )

    def _build_bundle(self, query: str, evidence: tuple[RAGEvidenceRecord, ...]) -> EvidenceBundle:
        return EvidenceBundle(
            query=query,
            evidence_count=len(evidence),
            evidence=evidence,
            source_count=len({item.source_id for item in evidence if item.source_id.strip()}),
            document_count=len({item.document_id for item in evidence if item.document_id.strip()}),
        )

    def _build_query_result(self, query: str, results: tuple[RAGResult, ...]) -> RAGQueryResult:
        return RAGQueryResult(query=query, results=results)

    def _build_malformed_resolved_company(self) -> ResolvedCompany:
        malformed_company = object.__new__(ResolvedCompany)
        object.__setattr__(malformed_company, "company_name", "   ")
        object.__setattr__(malformed_company, "ticker", "AAPL")
        object.__setattr__(malformed_company, "cik", "0000320193")
        object.__setattr__(malformed_company, "exchange", None)
        object.__setattr__(malformed_company, "country", None)
        object.__setattr__(malformed_company, "security_type", None)
        object.__setattr__(malformed_company, "company_id", None)
        object.__setattr__(malformed_company, "website_url", None)
        return malformed_company

    def _load_validate_company_node(self):
        module_path = Path("app/nodes/validate_company_node.py")
        spec = importlib.util.spec_from_file_location("test_validate_company_node", module_path)
        if spec is None or spec.loader is None:
            raise AssertionError("could not load validate_company_node module.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build_validate_company_node()

    def _build_workflow(
        self,
        *,
        resolver: RecordingCompanyResolver | None = None,
        rag_query_dependency: RecordingRAGQueryDependency | None = None,
        evidence_dependency: RecordingEvidenceAssemblyDependency | None = None,
        rag_result: RAGQueryResult | None = None,
        evidence_bundle: EvidenceBundle | None = None,
        rag_error: Exception | None = None,
        evidence_error: Exception | None = None,
        max_evidence: int = 3,
        minimum_similarity_score: float | None = 0.75,
        rag_top_k: int = 7,
    ):
        from app.graph.workflow import build_research_workflow

        resolver = resolver or RecordingCompanyResolver(self.resolved_company)
        rag_query_dependency = rag_query_dependency or RecordingRAGQueryDependency(result=rag_result, error=rag_error)
        evidence_dependency = evidence_dependency or RecordingEvidenceAssemblyDependency(
            result=evidence_bundle,
            error=evidence_error,
        )
        return build_research_workflow(
            company_resolution_dependency=resolver,
            runtime_config=self.runtime_config,
            sec_client=self.sec_client,
            embedding_service=self.embedding_service,
            vector_query_service=self.vector_query_service,
            rag_top_k=rag_top_k,
            max_evidence=max_evidence,
            query_dependency=rag_query_dependency,
            rag_metadata_filter=self.metadata_filter,
            rag_namespace_prefix=self.namespace_prefix,
            assemble_evidence_dependency=evidence_dependency,
            minimum_similarity_score=minimum_similarity_score,
        )

    def test_graph_builds_compiles_and_registers_expected_nodes(self) -> None:
        workflow = self._build_workflow(
            rag_result=self._build_query_result("Assess Apple", (self._build_rag_result("Assess Apple"),)),
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        graph = workflow.get_graph()
        self.assertEqual(
            set(graph.nodes),
            {
                "__start__",
                "initialize_research",
                "resolve_company",
                "validate_company",
                "retrieve_research",
                "assemble_evidence",
                "complete_workflow",
                "fail_workflow",
                "__end__",
            },
        )

        edge_pairs = {(edge.source, edge.target, edge.conditional) for edge in graph.edges}
        self.assertIn(("__start__", "initialize_research", False), edge_pairs)
        self.assertIn(("initialize_research", "resolve_company", True), edge_pairs)
        self.assertIn(("initialize_research", "fail_workflow", True), edge_pairs)
        self.assertIn(("resolve_company", "validate_company", True), edge_pairs)
        self.assertIn(("resolve_company", "fail_workflow", True), edge_pairs)
        self.assertIn(("validate_company", "retrieve_research", True), edge_pairs)
        self.assertIn(("validate_company", "fail_workflow", True), edge_pairs)
        self.assertIn(("retrieve_research", "assemble_evidence", True), edge_pairs)
        self.assertIn(("retrieve_research", "fail_workflow", True), edge_pairs)
        self.assertIn(("assemble_evidence", "complete_workflow", True), edge_pairs)
        self.assertIn(("assemble_evidence", "fail_workflow", True), edge_pairs)
        self.assertIn(("complete_workflow", "__end__", False), edge_pairs)
        self.assertIn(("fail_workflow", "__end__", False), edge_pairs)

        for forbidden_node in ("provider_collection", "rag", "evidence", "report", "react_agent"):
            self.assertNotIn(forbidden_node, graph.nodes)

    def test_graph_does_not_compile_during_import(self) -> None:
        import app.graph.workflow as workflow_module

        compiled_graphs = [
            value
            for value in vars(workflow_module).values()
            if value.__class__.__name__ == "CompiledStateGraph"
        ]
        self.assertEqual(compiled_graphs, [])

    def test_successful_execution_preserves_input_and_approved_outputs(self) -> None:
        query = "  Assess Apple Inc.  "
        rag_query_result = self._build_query_result(query, (self._build_rag_result(query),))
        evidence_bundle = self._build_bundle(query, (self._build_evidence_record(query),))
        resolver = RecordingCompanyResolver(self.resolved_company)
        rag_dependency = RecordingRAGQueryDependency(result=rag_query_result)
        evidence_dependency = RecordingEvidenceAssemblyDependency(result=evidence_bundle)
        workflow = self._build_workflow(
            resolver=resolver,
            rag_query_dependency=rag_dependency,
            evidence_dependency=evidence_dependency,
        )
        initial_state = {
            "research_query": query,
            "company_input": "  Apple Inc.  ",
        }
        original_state = dict(initial_state)

        result = workflow.invoke(initial_state)

        self.assertEqual(initial_state, original_state)
        self.assertEqual(len(resolver.calls), 1)
        request, runtime_config, sec_client = resolver.calls[0]
        self.assertEqual(request.company_name, "  Apple Inc.  ")
        self.assertIs(runtime_config, self.runtime_config)
        self.assertIs(sec_client, self.sec_client)

        self.assertEqual(len(rag_dependency.calls), 1)
        rag_call = rag_dependency.calls[0]
        self.assertEqual(rag_call[0], query)
        self.assertIs(rag_call[1], self.resolved_company)
        self.assertIs(rag_call[2], self.embedding_service)
        self.assertIs(rag_call[3], self.vector_query_service)
        self.assertEqual(rag_call[4], 7)
        self.assertEqual(rag_call[5], self.metadata_filter)
        self.assertEqual(rag_call[6], self.namespace_prefix)

        self.assertEqual(len(evidence_dependency.calls), 1)
        evidence_call = evidence_dependency.calls[0]
        self.assertIs(evidence_call[0], rag_query_result)
        self.assertEqual(evidence_call[1], 3)
        self.assertEqual(evidence_call[2], 0.75)

        self.assertEqual(result["research_query"], query)
        self.assertEqual(result["company_input"], "  Apple Inc.  ")
        self.assertEqual(result["resolved_company"], self.resolved_company)
        self.assertIs(result["rag_query_result"], rag_query_result)
        self.assertIs(result["evidence_bundle"], evidence_bundle)
        self.assertEqual(result["workflow_status"], "completed")
        self.assertEqual(result["current_stage"], "completed")
        self.assertEqual(result["errors"], ())

    def test_empty_rag_results_remain_successful(self) -> None:
        query = "Assess Apple"
        rag_query_result = self._build_query_result(query, ())
        evidence_bundle = self._build_bundle(query, ())
        workflow = self._build_workflow(
            rag_result=rag_query_result,
            evidence_bundle=evidence_bundle,
        )

        result = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "completed")
        self.assertEqual(result["current_stage"], "completed")
        self.assertEqual(result["evidence_bundle"], evidence_bundle)
        self.assertEqual(result["evidence_bundle"].evidence, ())
        self.assertEqual(result["evidence_bundle"].evidence_count, 0)

    def test_invalid_research_query_routes_to_failure_before_resolution(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver=resolver)

        result = workflow.invoke({"research_query": "", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 0)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_research_query")
        self.assertNotIn("resolved_company", result)

    def test_invalid_company_input_routes_to_failure_before_resolution(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver=resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": ""})

        self.assertEqual(len(resolver.calls), 0)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_company_input")
        self.assertNotIn("resolved_company", result)

    def test_retrieval_failure_routes_to_failure_without_evidence_call(self) -> None:
        workflow = self._build_workflow(
            rag_error=RAGQueryInputError("query invalid"),
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "RAGQueryInputError")
        self.assertNotIn("rag_query_result", result)
        self.assertNotIn("evidence_bundle", result)

    def test_retrieval_failure_records_direct_typed_error_type(self) -> None:
        workflow = self._build_workflow(
            rag_error=RAGEmbeddingError("RAG query embedding failed."),
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        error = result["errors"][0]
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(error.code, "RAGEmbeddingError")
        self.assertEqual(error.message, "Research retrieval failed.")
        self.assertEqual(error.details, (("stage", "retrieving_research"), ("error_type", "RAGEmbeddingError")))
        self.assertNotIn("rag_query_result", result)
        self.assertNotIn("evidence_bundle", result)

    def test_retrieval_failure_records_immediate_cause_error_type(self) -> None:
        cause = OpenAIEmbeddingsTransportError("OpenAI embeddings request failed.")
        
        def rag_dependency(
            query: str,
            resolved_company: ResolvedCompany,
            embedding_service,
            vector_query_service,
            *,
            top_k: int,
            metadata_filter=None,
            namespace_prefix=None,
        ) -> RAGQueryResult:
            del query, resolved_company, embedding_service, vector_query_service, top_k, metadata_filter, namespace_prefix
            raise RAGQueryError("RAG query orchestration failed.") from cause

        workflow = self._build_workflow(
            rag_query_dependency=rag_dependency,
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        error = result["errors"][0]
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(error.code, "RAGQueryError")
        self.assertEqual(error.message, "Research retrieval failed.")
        self.assertEqual(
            error.details,
            (("stage", "retrieving_research"), ("error_type", "OpenAIEmbeddingsTransportError")),
        )
        self.assertNotIn("rag_query_result", result)
        self.assertNotIn("evidence_bundle", result)

    def test_retrieval_consistency_failures_record_concrete_typed_error_names(self) -> None:
        for rag_error, expected_code in (
            (RAGQueryResponseConsistencyError("RAG Pinecone query returned an invalid response object."), "RAGQueryResponseConsistencyError"),
            (RAGQueryNamespaceConsistencyError("RAG Pinecone query returned a mismatched namespace."), "RAGQueryNamespaceConsistencyError"),
        ):
            with self.subTest(expected_code=expected_code):
                workflow = self._build_workflow(
                    rag_error=rag_error,
                    evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
                )

                result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

                error = result["errors"][0]
                self.assertEqual(result["workflow_status"], "failed")
                self.assertEqual(result["current_stage"], "failed")
                self.assertEqual(error.code, "RAGQueryError")
                self.assertEqual(error.message, "Research retrieval failed.")
                self.assertEqual(error.details, (("stage", "retrieving_research"), ("error_type", expected_code)))
                self.assertNotIn("rag_query_result", result)
                self.assertNotIn("evidence_bundle", result)

    def test_retrieval_failure_without_cause_records_own_class_name(self) -> None:
        workflow = self._build_workflow(
            rag_error=RAGQueryError("RAG query orchestration failed."),
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        error = result["errors"][0]
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(error.code, "RAGQueryError")
        self.assertEqual(error.message, "Research retrieval failed.")
        self.assertEqual(error.details, (("stage", "retrieving_research"), ("error_type", "RAGQueryError")))
        self.assertNotIn("rag_query_result", result)
        self.assertNotIn("evidence_bundle", result)

    def test_company_resolution_failure_routes_to_failure_before_validation(self) -> None:
        resolver = RecordingCompanyResolver(error=CompanyResolutionNoMatchError("No SEC company matched the supplied company name."))
        workflow = self._build_workflow(resolver=resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "CompanyResolutionNoMatchError")
        self.assertNotIn("resolved_company", result)

    def test_malformed_resolved_company_returned_by_resolution_node_routes_to_failure(self) -> None:
        resolver = RecordingCompanyResolver(result=self._build_malformed_resolved_company())
        workflow = self._build_workflow(resolver=resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_resolved_company")
        self.assertIs(result["resolved_company"], resolver.result)

    def test_validate_company_failure_path_routes_to_failure(self) -> None:
        validate_company = self._load_validate_company_node()
        malformed_company = self._build_malformed_resolved_company()

        result = validate_company(
            {
                "research_query": "Assess Apple",
                "company_input": "Apple Inc.",
                "resolved_company": malformed_company,
            }
        )

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_resolved_company")
        self.assertNotIn("resolved_company", result)

    def test_malformed_rag_query_output_routes_to_failure(self) -> None:
        workflow = self._build_workflow(
            rag_result=RAGQueryResult(query="Different query", results=()),
            evidence_bundle=self._build_bundle("Assess Apple", (self._build_evidence_record("Assess Apple"),)),
        )

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "malformed_rag_query_output")
        self.assertNotIn("rag_query_result", result)

    def test_evidence_failure_routes_to_failure_without_completion(self) -> None:
        query = "Assess Apple"
        rag_query_result = self._build_query_result(query, (self._build_rag_result(query),))
        workflow = self._build_workflow(
            rag_result=rag_query_result,
            evidence_error=EvidenceAssemblyInputError("evidence invalid"),
        )

        result = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "EvidenceAssemblyInputError")
        self.assertIs(result["rag_query_result"], rag_query_result)
        self.assertNotIn("evidence_bundle", result)

    def test_malformed_evidence_output_routes_to_failure(self) -> None:
        query = "Assess Apple"
        rag_query_result = self._build_query_result(query, (self._build_rag_result(query),))
        invalid_bundle = object.__new__(EvidenceBundle)
        object.__setattr__(invalid_bundle, "query", "Different query")
        object.__setattr__(invalid_bundle, "evidence_count", 1)
        object.__setattr__(invalid_bundle, "evidence", self._build_bundle(query, ()).evidence)
        object.__setattr__(invalid_bundle, "source_count", 0)
        object.__setattr__(invalid_bundle, "document_count", 0)
        workflow = self._build_workflow(
            rag_result=rag_query_result,
            evidence_bundle=invalid_bundle,
        )

        result = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "malformed_evidence_output")
        self.assertNotIn("evidence_bundle", result)

    def test_evidence_count_mismatch_routes_to_failure(self) -> None:
        query = "Assess Apple"
        rag_query_result = self._build_query_result(query, (self._build_rag_result(query),))
        invalid_bundle = object.__new__(EvidenceBundle)
        object.__setattr__(invalid_bundle, "query", query)
        object.__setattr__(invalid_bundle, "evidence_count", 2)
        evidence = (self._build_evidence_record(query),)
        object.__setattr__(invalid_bundle, "evidence", evidence)
        object.__setattr__(invalid_bundle, "source_count", 1)
        object.__setattr__(invalid_bundle, "document_count", 1)
        workflow = self._build_workflow(
            rag_result=rag_query_result,
            evidence_bundle=invalid_bundle,
        )

        result = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})

        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "malformed_evidence_output")
        self.assertNotIn("evidence_bundle", result)

    def test_repeated_invocations_are_deterministic(self) -> None:
        query = "Assess Apple"
        rag_query_result = self._build_query_result(query, (self._build_rag_result(query),))
        evidence_bundle = self._build_bundle(query, (self._build_evidence_record(query),))
        rag_dependency = RecordingRAGQueryDependency(result=rag_query_result)
        evidence_dependency = RecordingEvidenceAssemblyDependency(result=evidence_bundle)
        workflow = self._build_workflow(
            rag_query_dependency=rag_dependency,
            evidence_dependency=evidence_dependency,
        )

        first = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})
        second = workflow.invoke({"research_query": query, "company_input": "Apple Inc."})

        self.assertEqual(first, second)
        self.assertEqual(len(rag_dependency.calls), 2)
        self.assertEqual(len(evidence_dependency.calls), 2)

    def test_import_isolation_scan(self) -> None:
        sources = [
            Path("app/graph/state.py"),
            Path("app/graph/workflow.py"),
            Path("app/nodes/retrieve_research_node.py"),
            Path("app/nodes/assemble_evidence_node.py"),
        ]
        for path in sources:
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip().lower()
                self.assertFalse(stripped.startswith("import openai"))
                self.assertFalse(stripped.startswith("from openai"))
                self.assertFalse(stripped.startswith("import pinecone"))
                self.assertFalse(stripped.startswith("from pinecone"))
            lowered = source.lower()
            for pattern in (
                "alphavantage",
                "newsapi",
                "tavily",
                "react",
                "tool_registry",
                "report",
                "prompt",
                "exporter",
                "n8n",
                "os.environ",
                "os.getenv",
                "datetime.now",
                "uuid",
                "random",
            ):
                self.assertNotIn(pattern, lowered)

    def test_signature_does_not_require_state(self) -> None:
        from app.graph.workflow import build_research_workflow

        self.assertNotIn("state", inspect.signature(build_research_workflow).parameters)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
