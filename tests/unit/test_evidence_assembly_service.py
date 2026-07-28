"""Unit tests for deterministic evidence assembly."""

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

from app.models.providers import RAGResult
from app.services.evidence_assembly_service import (
    EvidenceAssemblyConsistencyError,
    EvidenceAssemblyInputError,
    EvidenceBundle,
    EvidenceRecord,
    assemble_evidence,
)
from app.services.rag_query_service import RAGQueryResult


class EvidenceAssemblyServiceTests(unittest.TestCase):
    """Offline tests for deterministic evidence assembly."""

    def _build_rag_result(
        self,
        *,
        result_id: str,
        company_name: str = "Apple Inc.",
        document_id: str = "doc-1",
        chunk_id: str = "chunk-1",
        source_id: str = "source-1",
        text: str = "Relevant retrieved passage.",
        similarity_score: float | None = 0.92,
        retrieval_scope: str | None = "company:cik:0000320193",
        source_url: str | None = "https://example.com/doc",
    ) -> RAGResult:
        return RAGResult(
            result_id=result_id,
            company_name=company_name,
            document_id=document_id,
            chunk_id=chunk_id,
            source_id=source_id,
            text=text,
            similarity_score=similarity_score,
            retrieval_scope=retrieval_scope,
            source_url=source_url,
        )

    def _build_query_result(self, results: tuple[RAGResult, ...], query: str = "Why does the company matter?") -> RAGQueryResult:
        return RAGQueryResult(query=query, results=results)

    def test_valid_query_result_selects_preserves_order_and_counts(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1", source_id="source-1", document_id="doc-1", chunk_id="chunk-1")
        result_2 = self._build_rag_result(result_id="result-2", source_id="source-2", document_id="doc-2", chunk_id="chunk-2")
        result_3 = self._build_rag_result(result_id="result-3", source_id="source-1", document_id="doc-1", chunk_id="chunk-3")
        query_result = self._build_query_result((result_1, result_2, result_3))

        bundle = assemble_evidence(query_result, max_evidence=2)

        self.assertIsInstance(bundle, EvidenceBundle)
        self.assertEqual(bundle.query, query_result.query)
        self.assertEqual(bundle.evidence_count, 2)
        self.assertEqual(bundle.source_count, 2)
        self.assertEqual(bundle.document_count, 2)
        self.assertEqual(tuple(item.result_id for item in bundle.evidence), ("result-1", "result-2"))
        self.assertEqual(bundle.evidence[0].text, result_1.text)
        self.assertEqual(bundle.evidence[1].text, result_2.text)

    def test_empty_results_return_empty_bundle(self) -> None:
        query_result = self._build_query_result(())

        bundle = assemble_evidence(query_result, max_evidence=5)

        self.assertEqual(bundle.query, query_result.query)
        self.assertEqual(bundle.evidence_count, 0)
        self.assertEqual(bundle.evidence, ())
        self.assertEqual(bundle.source_count, 0)
        self.assertEqual(bundle.document_count, 0)

    def test_wrong_input_type_rejected(self) -> None:
        with self.assertRaises(EvidenceAssemblyInputError):
            assemble_evidence(object(), max_evidence=1)  # type: ignore[arg-type]

    def test_blank_query_in_malformed_input_rejected(self) -> None:
        malformed = object.__new__(RAGQueryResult)
        object.__setattr__(malformed, "query", "   ")
        object.__setattr__(malformed, "results", ())

        with self.assertRaises(EvidenceAssemblyInputError):
            assemble_evidence(malformed, max_evidence=1)

    def test_invalid_results_collection_rejected(self) -> None:
        malformed = object.__new__(RAGQueryResult)
        object.__setattr__(malformed, "query", "Why does the company matter?")
        object.__setattr__(malformed, "results", [])

        with self.assertRaises(EvidenceAssemblyConsistencyError):
            assemble_evidence(malformed, max_evidence=1)

    def test_non_rag_result_item_rejected(self) -> None:
        malformed = object.__new__(RAGQueryResult)
        object.__setattr__(malformed, "query", "Why does the company matter?")
        object.__setattr__(malformed, "results", (object(),))

        with self.assertRaises(EvidenceAssemblyConsistencyError):
            assemble_evidence(malformed, max_evidence=1)

    def test_invalid_max_evidence_rejected(self) -> None:
        query_result = self._build_query_result((self._build_rag_result(result_id="result-1"),))

        for invalid in (0, -1, True, "2"):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(EvidenceAssemblyInputError):
                    assemble_evidence(query_result, max_evidence=invalid)

    def test_invalid_min_similarity_rejected(self) -> None:
        query_result = self._build_query_result((self._build_rag_result(result_id="result-1"),))

        for invalid in (True, "0.8", float("inf")):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(EvidenceAssemblyInputError):
                    assemble_evidence(query_result, max_evidence=1, minimum_similarity_score=invalid)

    def test_input_remains_unchanged(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1")
        result_2 = self._build_rag_result(result_id="result-2")
        query_result = self._build_query_result((result_1, result_2))
        snapshot = query_result.results

        bundle = assemble_evidence(query_result, max_evidence=2)

        self.assertIs(query_result.results, snapshot)
        self.assertIs(query_result.results[0], result_1)
        self.assertIs(query_result.results[1], result_2)
        self.assertEqual(bundle.query, query_result.query)

    def test_exact_duplicate_identity_is_deduplicated(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1")
        duplicate = self._build_rag_result(result_id="result-1")
        result_2 = self._build_rag_result(result_id="result-2")
        query_result = self._build_query_result((result_1, duplicate, result_2))

        bundle = assemble_evidence(query_result, max_evidence=5)

        self.assertEqual(tuple(item.result_id for item in bundle.evidence), ("result-1", "result-2"))

    def test_contradictory_duplicate_identity_raises_consistency_error(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1", text="First passage.")
        contradictory = self._build_rag_result(result_id="result-1", text="Different passage.")
        query_result = self._build_query_result((result_1, contradictory))

        with self.assertRaises(EvidenceAssemblyConsistencyError):
            assemble_evidence(query_result, max_evidence=5)

    def test_minimum_similarity_score_filters_and_preserves_order(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1", similarity_score=0.70)
        result_2 = self._build_rag_result(result_id="result-2", similarity_score=0.75)
        result_3 = self._build_rag_result(result_id="result-3", similarity_score=0.90)
        query_result = self._build_query_result((result_1, result_2, result_3))

        bundle = assemble_evidence(query_result, max_evidence=5, minimum_similarity_score=0.75)

        self.assertEqual(tuple(item.result_id for item in bundle.evidence), ("result-2", "result-3"))

    def test_low_scores_do_not_override_limit_or_sort(self) -> None:
        result_1 = self._build_rag_result(result_id="result-1", similarity_score=0.99)
        result_2 = self._build_rag_result(result_id="result-2", similarity_score=0.98)
        result_3 = self._build_rag_result(result_id="result-3", similarity_score=0.97)
        query_result = self._build_query_result((result_1, result_2, result_3))

        bundle = assemble_evidence(query_result, max_evidence=2)

        self.assertEqual(tuple(item.result_id for item in bundle.evidence), ("result-1", "result-2"))

    def test_evidence_record_and_bundle_are_immutable_and_serializable(self) -> None:
        result = self._build_rag_result(result_id="result-1")
        query_result = self._build_query_result((result,))
        bundle = assemble_evidence(query_result, max_evidence=1)
        evidence = bundle.evidence[0]

        with self.assertRaises(FrozenInstanceError):
            evidence.text = "changed"  # type: ignore[misc]

        with self.assertRaises(FrozenInstanceError):
            bundle.query = "changed"  # type: ignore[misc]

        json.dumps(asdict(evidence))
        json.dumps(asdict(bundle))

    def test_similarity_score_is_preserved_exactly(self) -> None:
        result = self._build_rag_result(result_id="result-1", similarity_score=0.875)
        query_result = self._build_query_result((result,))

        bundle = assemble_evidence(query_result, max_evidence=1)

        self.assertEqual(bundle.evidence[0].similarity_score, result.similarity_score)

    def test_bundle_does_not_store_raw_rag_result(self) -> None:
        result = self._build_rag_result(result_id="result-1")
        query_result = self._build_query_result((result,))

        bundle = assemble_evidence(query_result, max_evidence=1)

        self.assertFalse(any(isinstance(item, RAGResult) for item in bundle.evidence))
        self.assertFalse(hasattr(bundle.evidence[0], "metadata"))
        self.assertFalse(hasattr(bundle.evidence[0], "vector"))

    def test_errors_do_not_expose_content(self) -> None:
        malformed = object.__new__(RAGQueryResult)
        object.__setattr__(malformed, "query", "Why does the company matter?")
        object.__setattr__(malformed, "results", (object(),))

        with self.assertRaises(EvidenceAssemblyConsistencyError) as ctx:
            assemble_evidence(malformed, max_evidence=1)

        self.assertNotIn("Relevant retrieved passage.", str(ctx.exception))

    def test_import_isolation_scan(self) -> None:
        source = Path("app/services/evidence_assembly_service.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "openai",
            "pinecone",
            "embeddingservice",
            "vector_query",
            "retrieve_rag",
            "document_chunking",
            "vector_preparation",
            "vector_indexing",
            "langgraph",
            "app.models.state",
            "prompt",
            "report",
            "exporter",
            "n8n",
            "os.environ",
            "os.getenv",
            "datetime.now",
            "uuid",
            "random",
        ):
            self.assertNotIn(forbidden, source)

    def test_signature_has_no_state_input(self) -> None:
        self.assertNotIn("state", inspect.signature(assemble_evidence).parameters)
