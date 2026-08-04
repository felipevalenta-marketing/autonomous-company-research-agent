"""Unit tests for semantic RAG retrieval."""

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import asdict
from pathlib import Path

import httpx

from app.clients.openai_embedding_dtos import OpenAIEmbeddingItemDTO, OpenAIEmbeddingUsageDTO, OpenAIEmbeddingsResponseDTO
from app.clients.pinecone_client import PineconeClient
from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.config.defaults import PineconeConfig
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.rag.normalization import normalize_rag_results
from app.rag.retrieval_service import (
    RAGEmbeddingError,
    RAGQueryError,
    RAGQueryNamespaceConsistencyError,
    RAGQueryResponseConsistencyError,
    RAGRetrievalError,
    RAGRetrievalInputError,
    retrieve_rag_results,
)
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceError, EmbeddingServiceResult
from app.services.vector_preparation_service import build_pinecone_namespace
from app.services.vector_query_service import VectorQueryError, query_pinecone_vectors
from app.utils.hashing import sha256_text


class FakeEmbeddingService:
    """In-memory embedding service for offline tests."""

    def __init__(self, response: EmbeddingServiceResult | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[str] = []

    def __call__(self, query: str) -> EmbeddingServiceResult:
        self.calls.append(query)
        if self.exc is not None:
            raise self.exc
        if self.response is None:
            raise AssertionError("fake embedding service was not configured.")
        return self.response


class FakeVectorQueryService:
    """In-memory Pinecone query service for offline tests."""

    def __init__(self, response: PineconeQueryResponseDTO | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[tuple[tuple[float, ...], str, int, object]] = []

    def __call__(
        self,
        vector: tuple[float, ...],
        namespace: str,
        top_k: int,
        metadata_filter: object = None,
    ) -> PineconeQueryResponseDTO:
        self.calls.append((vector, namespace, top_k, metadata_filter))
        if self.exc is not None:
            raise self.exc
        if self.response is None:
            raise AssertionError("fake vector query service was not configured.")
        return self.response


class RAGRetrievalServiceTests(unittest.TestCase):
    """Offline tests for semantic retrieval orchestration."""

    def _build_embedding_result(self, query: str, vector: tuple[float, ...] = (0.1, 0.2, 0.3)) -> EmbeddingServiceResult:
        record = EmbeddingRecord(
            input_index=0,
            input_checksum=sha256_text(query),
            model="text-embedding-3-small",
            vector_dimension=len(vector),
            vector=vector,
        )
        return EmbeddingServiceResult(model="text-embedding-3-small", embeddings=(record,))

    def _build_company(self, *, cik: str | None = "0000320193", ticker: str | None = "AAPL") -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker=ticker, cik=cik)

    def _build_match(
        self,
        *,
        record_id: str = "match-1",
        score: float = 0.92,
        text: str = "Relevant retrieved passage.",
        document_id: str = "doc-1",
        chunk_id: str = "chunk-1",
        source_id: str = "source-1",
        source_url: str = "https://example.com/doc",
        company_name: str = "Apple Inc.",
        ticker: str = "AAPL",
        cik: str = "0000320193",
        content_checksum: str = "checksum-1",
    ) -> PineconeQueryMatchDTO:
        return PineconeQueryMatchDTO(
            record_id=record_id,
            score=score,
            metadata={
                "document_id": document_id,
                "chunk_id": chunk_id,
                "source_id": source_id,
                "text": text,
                "source_url": source_url,
                "company_name": company_name,
                "ticker": ticker,
                "cik": cik,
                "content_checksum": content_checksum,
            },
        )

    def test_valid_query_uses_embedding_and_query_once(self) -> None:
        query = "  Why does Apple's strategy matter?  "
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query.strip()))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace)
        )

        results = retrieve_rag_results(
            query,
            company,
            embedding_service,
            vector_query_service,
            top_k=5,
            metadata_filter={"source_id": "source-1"},
            namespace_prefix="company",
        )

        self.assertEqual(embedding_service.calls, [query.strip()])
        self.assertEqual(len(vector_query_service.calls), 1)
        vector, call_namespace, top_k, metadata_filter = vector_query_service.calls[0]
        self.assertEqual(vector, (0.1, 0.2, 0.3))
        self.assertEqual(call_namespace, namespace)
        self.assertEqual(top_k, 5)
        self.assertEqual(metadata_filter, {"source_id": "source-1"})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].company_name, "Apple Inc.")
        self.assertEqual(results[0].retrieval_scope, namespace)

    def test_retrieval_is_deterministic(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        response = PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace)
        vector_query_service = FakeVectorQueryService(response=response)

        first = retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")
        second = retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertEqual(first, second)

    def test_invalid_query_rejected(self) -> None:
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result("Apple strategy?"))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(), namespace=build_pinecone_namespace(company, "company"))
        )

        for invalid in ("", "   ", 123):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(RAGRetrievalInputError):
                    retrieve_rag_results(invalid, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

    def test_namespace_identity_priority(self) -> None:
        query = "Apple strategy?"
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))

        cik_company = self._build_company()
        ticker_only_company = self._build_company(cik=None)
        company_only = self._build_company(cik=None, ticker=None)

        class NamespaceEchoVectorQueryService:
            def __init__(self) -> None:
                self.calls: list[tuple[tuple[float, ...], str, int, object]] = []

            def __call__(
                self,
                vector: tuple[float, ...],
                namespace: str,
                top_k: int,
                metadata_filter: object = None,
            ) -> PineconeQueryResponseDTO:
                self.calls.append((vector, namespace, top_k, metadata_filter))
                return PineconeQueryResponseDTO(matches=(), namespace=namespace)

        vector_query_service = NamespaceEchoVectorQueryService()

        retrieve_rag_results(query, cik_company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")
        self.assertEqual(vector_query_service.calls[-1][1], build_pinecone_namespace(cik_company, "company"))

        retrieve_rag_results(query, ticker_only_company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")
        self.assertEqual(vector_query_service.calls[-1][1], build_pinecone_namespace(ticker_only_company, "company"))

        retrieve_rag_results(query, company_only, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")
        self.assertEqual(vector_query_service.calls[-1][1], build_pinecone_namespace(company_only, "company"))

    def test_zero_match_response_is_empty(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace=namespace))

        results = retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertEqual(results, ())

    def test_embedding_error_propagates(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(exc=EmbeddingServiceError("embedding failed"))
        vector_query_service = FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc"))

        with self.assertRaises(RAGEmbeddingError):
            retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

    def test_vector_query_error_propagates(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(exc=VectorQueryError("query failed"))

        with self.assertRaises(RAGQueryError):
            retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

    def test_invalid_query_response_object_raises_response_consistency_error_without_cause(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(response=object())  # type: ignore[arg-type]

        with self.assertRaises(RAGQueryResponseConsistencyError) as context:
            retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertTrue(issubclass(RAGQueryResponseConsistencyError, RAGQueryError))
        self.assertIsNone(context.exception.__cause__)
        self.assertEqual(vector_query_service.calls[-1][1], namespace)

    def test_mismatched_namespace_raises_namespace_consistency_error_without_cause(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace="company:cik:wrong")
        )

        with self.assertRaises(RAGQueryNamespaceConsistencyError) as context:
            retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertTrue(issubclass(RAGQueryNamespaceConsistencyError, RAGQueryError))
        self.assertIsNone(context.exception.__cause__)
        self.assertEqual(len(vector_query_service.calls), 1)

    def test_retrieval_result_does_not_mutate_state_or_require_state(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace))
        state = {"rag_results": []}
        snapshot = dict(state)

        retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertEqual(state, snapshot)
        self.assertNotIn("state", inspect.signature(retrieve_rag_results).parameters)

    def test_import_isolation_scan(self) -> None:
        source = Path("app/rag/retrieval_service.py").read_text(encoding="utf-8")
        for forbidden in (
            "langgraph",
            "app.models.state",
            "report",
            "prompts",
            "exporters",
            "n8n",
            "OpenAIEmbeddingsClient(",
            "PineconeClient(",
        ):
            self.assertNotIn(forbidden, source)

    def test_package_init_import_isolation_scan(self) -> None:
        source = Path("app/rag/__init__.py").read_text(encoding="utf-8")
        for forbidden in (
            "langgraph",
            "app.models.state",
            "OpenAIEmbeddingsClient(",
            "PineconeClient(",
            "report",
            "prompts",
            "exporters",
            "n8n",
        ):
            self.assertNotIn(forbidden, source)

    def test_json_serializable(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace))

        results = retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")
        json.dumps([asdict(result) for result in results])

    def test_empty_pinecone_values_are_treated_as_absent_through_real_client(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/query")
            return httpx.Response(
                200,
                json={
                    "matches": [
                        {
                            "id": "vec-1",
                            "score": 0.9,
                            "metadata": {
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
                            "values": [],
                        }
                    ],
                    "namespace": namespace,
                },
            )

        runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")
        pinecone_config = PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=3,
            api_version="2024-07",
            max_upsert_batch_size=100,
            max_query_top_k=5,
        )
        pinecone_client = PineconeClient(
            runtime_config=runtime_config,
            pinecone_config=pinecone_config,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        def vector_query_service(vector, namespace_value, top_k, metadata_filter):  # noqa: ANN001
            return query_pinecone_vectors(vector, pinecone_client, namespace_value, pinecone_config, top_k=top_k, filter=metadata_filter)

        results = retrieve_rag_results(query, company, embedding_service, vector_query_service, top_k=4, namespace_prefix="company")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].retrieval_scope, namespace)
        self.assertEqual(results[0].source_id, "source-1")
