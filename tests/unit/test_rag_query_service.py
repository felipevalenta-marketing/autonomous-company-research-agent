"""Unit tests for the RAG query orchestration service."""

from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.models.company import ResolvedCompany
from app.models.providers import RAGResult
from app.rag.retrieval_service import (
    RAGEmbeddingError,
    RAGQueryError as RetrievalRAGQueryError,
    RAGQueryNamespaceConsistencyError,
    RAGQueryResponseConsistencyError,
)
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceError, EmbeddingServiceResult
from app.services.rag_query_service import (
    RAGQueryConsistencyError,
    RAGQueryInputError,
    RAGQueryResult,
    query_company_rag,
)
from app.services.vector_preparation_service import build_pinecone_namespace
from app.services.vector_query_service import VectorQueryError
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


class FakeRetrievalService:
    """In-memory retrieval boundary for orchestration tests."""

    def __init__(self, response: object = (), exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, ResolvedCompany, object, object, int, object, object]] = []

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
    ) -> object:
        self.calls.append((query, resolved_company, embedding_service, vector_query_service, top_k, metadata_filter, namespace_prefix))
        if self.exc is not None:
            raise self.exc
        return self.response


class RagQueryServiceTests(unittest.TestCase):
    """Offline tests for RAG query orchestration."""

    def _build_company(self) -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def _build_embedding_result(self, query: str, vector: tuple[float, ...] = (0.1, 0.2, 0.3)) -> EmbeddingServiceResult:
        record = EmbeddingRecord(
            input_index=0,
            input_checksum=sha256_text(query),
            model="text-embedding-3-small",
            vector_dimension=len(vector),
            vector=vector,
        )
        return EmbeddingServiceResult(model="text-embedding-3-small", embeddings=(record,))

    def _build_match(self) -> PineconeQueryMatchDTO:
        return PineconeQueryMatchDTO(
            record_id="match-1",
            score=0.93,
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

    def test_valid_query_delegates_once_and_preserves_original_query(self) -> None:
        query = "  Why does Apple's strategy matter?  "
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query.strip()))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace)
        )

        result = query_company_rag(
            query,
            company,
            embedding_service,
            vector_query_service,
            top_k=5,
            metadata_filter={"source_id": "source-1"},
            namespace_prefix="company",
        )

        self.assertIsInstance(result, RAGQueryResult)
        self.assertEqual(result.query, query)
        self.assertEqual(result.results[0].company_name, "Apple Inc.")
        self.assertEqual(embedding_service.calls, [query.strip()])
        self.assertEqual(len(vector_query_service.calls), 1)
        vector, call_namespace, top_k, metadata_filter = vector_query_service.calls[0]
        self.assertEqual(vector, (0.1, 0.2, 0.3))
        self.assertEqual(call_namespace, namespace)
        self.assertEqual(top_k, 5)
        self.assertEqual(metadata_filter, {"source_id": "source-1"})

    def test_query_is_deterministic(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(self._build_match(),), namespace=namespace)
        )

        first = query_company_rag(
            query,
            company,
            embedding_service,
            vector_query_service,
            top_k=4,
            namespace_prefix="company",
        )
        second = query_company_rag(
            query,
            company,
            embedding_service,
            vector_query_service,
            top_k=4,
            namespace_prefix="company",
        )

        self.assertEqual(first, second)

    def test_query_is_forwarded_to_retrieval_unchanged(self) -> None:
        query = "  Why does Apple's strategy matter?  "
        company = self._build_company()
        retrieval_service = FakeRetrievalService(response=())
        namespace = build_pinecone_namespace(company, "company")

        result = query_company_rag(
            query,
            company,
            FakeEmbeddingService(response=self._build_embedding_result(query.strip())),
            FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace=namespace)),
            top_k=4,
            namespace_prefix="company",
            retrieval_service=retrieval_service,
        )

        self.assertEqual(retrieval_service.calls[0][0], query)
        self.assertEqual(result.query, query)
        self.assertEqual(result.results, ())

    def test_invalid_query_rejected_before_dependencies_run(self) -> None:
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result("Apple strategy?"))
        namespace = build_pinecone_namespace(company, "company")
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(), namespace=namespace)
        )

        for invalid in ("", "   ", 123):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(RAGQueryInputError):
                    query_company_rag(
                        invalid,
                        company,
                        embedding_service,
                        vector_query_service,
                        top_k=4,
                        namespace_prefix="company",
                    )

        self.assertEqual(embedding_service.calls, [])
        self.assertEqual(vector_query_service.calls, [])

    def test_invalid_company_rejected_before_dependencies_run(self) -> None:
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result("Apple strategy?"))
        namespace = build_pinecone_namespace(self._build_company(), "company")
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(), namespace=namespace)
        )

        with self.assertRaises(RAGQueryInputError):
            query_company_rag(
                "Apple strategy?",
                object(),  # type: ignore[arg-type]
                embedding_service,
                vector_query_service,
                top_k=4,
                namespace_prefix="company",
            )

        self.assertEqual(embedding_service.calls, [])
        self.assertEqual(vector_query_service.calls, [])

    def test_empty_retrieval_result_returns_empty_tuple(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(), namespace=namespace)
        )

        result = query_company_rag(
            query,
            company,
            embedding_service,
            vector_query_service,
            top_k=4,
            namespace_prefix="company",
        )

        self.assertEqual(result.results, ())
        self.assertIsInstance(result.results, tuple)

    def test_embedding_failure_prevents_retrieval(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(exc=EmbeddingServiceError("embedding failed"))
        namespace = build_pinecone_namespace(company, "company")
        vector_query_service = FakeVectorQueryService(
            response=PineconeQueryResponseDTO(matches=(), namespace=namespace)
        )

        with self.assertRaises(RAGEmbeddingError):
            query_company_rag(
                query,
                company,
                embedding_service,
                vector_query_service,
                top_k=4,
                namespace_prefix="company",
            )

        self.assertEqual(len(vector_query_service.calls), 0)

    def test_retrieval_error_remains_distinguishable(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        namespace = build_pinecone_namespace(company, "company")
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        vector_query_service = FakeVectorQueryService(exc=VectorQueryError("query failed"))

        with self.assertRaises(RetrievalRAGQueryError):
            query_company_rag(
                query,
                company,
                embedding_service,
                vector_query_service,
                top_k=4,
                namespace_prefix="company",
            )

    def test_retrieval_consistency_errors_pass_through_unchanged(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        retrieval_service = FakeRetrievalService(
            exc=RAGQueryResponseConsistencyError("RAG Pinecone query returned an invalid response object.")
        )

        with self.assertRaises(RAGQueryResponseConsistencyError) as response_context:
            query_company_rag(
                query,
                company,
                embedding_service,
                FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace=build_pinecone_namespace(company, "company"))),
                top_k=4,
                namespace_prefix="company",
                retrieval_service=retrieval_service,
            )

        self.assertIsNone(response_context.exception.__cause__)

        retrieval_service = FakeRetrievalService(
            exc=RAGQueryNamespaceConsistencyError("RAG Pinecone query returned a mismatched namespace.")
        )

        with self.assertRaises(RAGQueryNamespaceConsistencyError) as namespace_context:
            query_company_rag(
                query,
                company,
                embedding_service,
                FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace=build_pinecone_namespace(company, "company"))),
                top_k=4,
                namespace_prefix="company",
                retrieval_service=retrieval_service,
            )

        self.assertIsNone(namespace_context.exception.__cause__)

    def test_malformed_retrieval_output_fails_safely(self) -> None:
        query = "Apple strategy?"
        company = self._build_company()
        embedding_service = FakeEmbeddingService(response=self._build_embedding_result(query))
        retrieval_service = FakeRetrievalService(response=[RAGResult(
            result_id="result-1",
            company_name="Apple Inc.",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_id="source-1",
            text="Relevant retrieved passage.",
        )])

        with self.assertRaises(RAGQueryConsistencyError):
            query_company_rag(
                query,
                company,
                embedding_service,
                FakeVectorQueryService(response=PineconeQueryResponseDTO(matches=(), namespace=build_pinecone_namespace(company, "company"))),
                top_k=4,
                namespace_prefix="company",
                retrieval_service=retrieval_service,
            )

        self.assertEqual(len(retrieval_service.calls), 1)

    def test_result_is_immutable(self) -> None:
        result = RAGQueryResult(query="Apple strategy?", results=())

        with self.assertRaises(FrozenInstanceError):
            result.query = "changed"  # type: ignore[misc]

    def test_import_isolation_scan(self) -> None:
        source = Path("app/services/rag_query_service.py").read_text(encoding="utf-8")
        lowered = source.lower()
        for line in lowered.splitlines():
            stripped = line.strip()
            self.assertFalse(stripped.startswith("import pinecone"))
            self.assertFalse(stripped.startswith("from pinecone"))
        for forbidden in (
            "pinecone(",
            "index(",
            "langgraph",
            "app.models.state",
            "report",
            "prompt",
            "exporter",
            "n8n",
            "os.environ",
            "os.getenv",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_signature_does_not_require_state(self) -> None:
        self.assertNotIn("state", inspect.signature(query_company_rag).parameters)
