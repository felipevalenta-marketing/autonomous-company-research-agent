"""Unit tests for RAG normalization."""

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.models.company import ResolvedCompany
from app.models.providers import RAGResult
from app.rag.normalization import RAGMetadataError, RAGScoreError, normalize_rag_results
from app.utils.hashing import sha256_text


class RAGNormalizationTests(unittest.TestCase):
    """Offline tests for canonical RAG normalization."""

    def _build_company(self) -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def _build_match(
        self,
        *,
        record_id: str = "match-1",
        score: float = 0.91,
        text: str | None = "Relevant retrieved passage.",
        source_url: str = "https://example.com/doc",
        document_id: str = "doc-1",
        chunk_id: str = "chunk-1",
        source_id: str = "source-1",
        company_name: str = "Apple Inc.",
        ticker: str = "AAPL",
        cik: str = "0000320193",
        content_checksum: str | None = None,
    ) -> PineconeQueryMatchDTO:
        metadata: dict[str, object] = {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "source_id": source_id,
            "company_name": company_name,
            "ticker": ticker,
            "cik": cik,
            "source_url": source_url,
            "provider_name": "Pinecone",
        }
        if text is not None:
            metadata["text"] = text
        if content_checksum is not None:
            metadata["content_checksum"] = content_checksum
        return PineconeQueryMatchDTO(record_id=record_id, score=score, metadata=metadata)

    def test_valid_match_creates_rag_result(self) -> None:
        company = self._build_company()
        match = self._build_match(content_checksum="checksum-1")
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        results = normalize_rag_results(company, response)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertIsInstance(result, RAGResult)
        self.assertEqual(result.company_name, "Apple Inc.")
        self.assertEqual(result.document_id, "doc-1")
        self.assertEqual(result.chunk_id, "chunk-1")
        self.assertEqual(result.source_id, "source-1")
        self.assertEqual(result.text, "Relevant retrieved passage.")
        self.assertEqual(result.similarity_score, 0.91)
        self.assertEqual(result.source_url, "https://example.com/doc")
        self.assertEqual(result.retrieval_scope, "company:cik:abc")
        self.assertEqual(result.result_id, sha256_text("source-1|doc-1|chunk-1|checksum-1"))

    def test_missing_required_text_excludes_match(self) -> None:
        company = self._build_company()
        match = self._build_match(text=None)
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        results = normalize_rag_results(company, response)

        self.assertEqual(results, ())

    def test_company_identity_mismatch_raises(self) -> None:
        company = self._build_company()
        match = self._build_match(company_name="Different Corp.")
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        with self.assertRaises(RAGMetadataError):
            normalize_rag_results(company, response)

    def test_malformed_metadata_raises(self) -> None:
        company = self._build_company()
        match = self._build_match()
        object.__setattr__(match, "metadata", {"source_id": {"nested": 1}})
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        with self.assertRaises(RAGMetadataError):
            normalize_rag_results(company, response)

    def test_non_finite_score_raises(self) -> None:
        company = self._build_company()
        match = self._build_match()
        object.__setattr__(match, "score", float("nan"))
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        with self.assertRaises(RAGScoreError):
            normalize_rag_results(company, response)

    def test_duplicate_canonical_ids_keep_highest_score(self) -> None:
        company = self._build_company()
        low = self._build_match(record_id="match-low", score=0.4, content_checksum="checksum-dup")
        high = self._build_match(record_id="match-high", score=0.9, content_checksum="checksum-dup")
        response = PineconeQueryResponseDTO(matches=(low, high), namespace="company:cik:abc")

        results = normalize_rag_results(company, response)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].similarity_score, 0.9)

    def test_equal_score_ordering_is_deterministic(self) -> None:
        company = self._build_company()
        first = self._build_match(record_id="match-b", score=0.8, content_checksum="checksum-a")
        second = self._build_match(record_id="match-a", score=0.8, content_checksum="checksum-b")
        response = PineconeQueryResponseDTO(matches=(first, second), namespace="company:cik:abc")

        results = normalize_rag_results(company, response)

        self.assertEqual([result.result_id for result in results], sorted(result.result_id for result in results))

    def test_score_ordering_prefers_higher_score(self) -> None:
        company = self._build_company()
        lower = self._build_match(record_id="match-low", score=0.3, content_checksum="checksum-low")
        higher = self._build_match(record_id="match-high", score=0.9, content_checksum="checksum-high")
        response = PineconeQueryResponseDTO(matches=(lower, higher), namespace="company:cik:abc")

        results = normalize_rag_results(company, response)

        self.assertEqual([result.similarity_score for result in results], [0.9, 0.3])

    def test_json_serializable(self) -> None:
        company = self._build_company()
        response = PineconeQueryResponseDTO(matches=(self._build_match(),), namespace="company:cik:abc")
        results = normalize_rag_results(company, response)

        json.dumps([asdict(result) for result in results])

    def test_no_forbidden_imports_in_source(self) -> None:
        source = Path("app/rag/normalization.py").read_text(encoding="utf-8")
        for forbidden in (
            "langgraph",
            "app.models.state",
            "OpenAIEmbeddingsClient(",
            "PineconeClient(",
            "report_generation",
            "prompts",
            "exporters",
            "n8n",
        ):
            self.assertNotIn(forbidden, source)

    def test_signature_has_no_state_input(self) -> None:
        parameters = inspect.signature(normalize_rag_results).parameters
        self.assertNotIn("state", parameters)
