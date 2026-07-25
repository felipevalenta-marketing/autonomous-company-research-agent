"""Unit tests for Pinecone vector preparation."""

from __future__ import annotations

import unittest

from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.models.company import ResolvedCompany
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceResult
from app.services.vector_preparation_service import (
    VectorDimensionError,
    VectorMetadataError,
    VectorPreparationInputError,
    build_pinecone_namespace,
    prepare_pinecone_vectors,
)


class VectorPreparationServiceTests(unittest.TestCase):
    """Offline tests for deterministic Pinecone vector preparation."""

    def _build_embedding_result(self) -> EmbeddingServiceResult:
        return EmbeddingServiceResult(
            model="text-embedding-3-small",
            embeddings=(
                EmbeddingRecord(
                    input_index=0,
                    input_checksum="checksum-1",
                    model="text-embedding-3-small",
                    vector_dimension=3,
                    vector=(0.1, 0.2, 0.3),
                ),
                EmbeddingRecord(
                    input_index=1,
                    input_checksum="checksum-2",
                    model="text-embedding-3-small",
                    vector_dimension=3,
                    vector=(0.4, 0.5, 0.6),
                ),
            ),
        )

    def test_matching_input_lengths_prepare_records(self) -> None:
        result = prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"document_id": "doc-1", "source_id": "source-1"},
                {"document_id": "doc-2", "source_id": "source-2"},
            ),
            expected_dimension=3,
        )

        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], PineconeVectorRecordDTO)
        self.assertEqual(result[0].values, (0.1, 0.2, 0.3))
        self.assertEqual(result[0].metadata["input_index"], 0)
        self.assertEqual(result[0].metadata["input_checksum"], "checksum-1")
        self.assertEqual(result[0].metadata["embedding_model"], "text-embedding-3-small")

    def test_mismatched_lengths_rejected(self) -> None:
        with self.assertRaises(VectorPreparationInputError):
            prepare_pinecone_vectors(
                self._build_embedding_result(),
                ("doc-1",),
                ({"document_id": "doc-1"},),
                expected_dimension=3,
            )

    def test_stable_identity_is_required(self) -> None:
        with self.assertRaises(VectorPreparationInputError):
            prepare_pinecone_vectors(
                self._build_embedding_result(),
                ("doc-1", " "),
                (
                    {"document_id": "doc-1"},
                    {"document_id": "doc-2"},
                ),
                expected_dimension=3,
            )

    def test_deterministic_record_ids(self) -> None:
        first = prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"document_id": "doc-1"},
                {"document_id": "doc-2"},
            ),
            expected_dimension=3,
        )
        second = prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"document_id": "doc-1"},
                {"document_id": "doc-2"},
            ),
            expected_dimension=3,
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first[0].record_id, first[1].record_id)

    def test_input_order_is_preserved(self) -> None:
        result = prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"document_id": "doc-1"},
                {"document_id": "doc-2"},
            ),
            expected_dimension=3,
        )

        self.assertEqual([record.metadata["input_index"] for record in result], [0, 1])

    def test_dimension_validation(self) -> None:
        with self.assertRaises(VectorDimensionError):
            prepare_pinecone_vectors(
                self._build_embedding_result(),
                ("doc-1", "doc-2"),
                (
                    {"document_id": "doc-1"},
                    {"document_id": "doc-2"},
                ),
                expected_dimension=2,
            )

    def test_metadata_sanitization(self) -> None:
        result = prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"text_id": ["chunk-1", "chunk-2"]},
                {"text_id": ["chunk-3"]},
            ),
            expected_dimension=3,
        )

        self.assertEqual(result[0].metadata["text_id"], ("chunk-1", "chunk-2"))

    def test_invalid_metadata_key_rejected(self) -> None:
        with self.assertRaises(VectorMetadataError):
            prepare_pinecone_vectors(
                self._build_embedding_result(),
                ("doc-1", "doc-2"),
                (
                    {"unsupported": "value"},
                    {"document_id": "doc-2"},
                ),
                expected_dimension=3,
            )

    def test_namespace_uses_cik_then_ticker_then_company_name(self) -> None:
        cik_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193"),
            "company",
        )
        ticker_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Apple Inc.", ticker="AAPL"),
            "company",
        )
        company_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Apple Inc."),
            "company",
        )

        self.assertEqual(cik_namespace, build_pinecone_namespace(ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193"), "company"))
        self.assertNotEqual(cik_namespace, ticker_namespace)
        self.assertNotEqual(ticker_namespace, company_namespace)
        self.assertTrue(cik_namespace.startswith("company:"))

    def test_no_shared_state_mutation(self) -> None:
        state = {"records": []}
        prepare_pinecone_vectors(
            self._build_embedding_result(),
            ("doc-1", "doc-2"),
            (
                {"document_id": "doc-1"},
                {"document_id": "doc-2"},
            ),
            expected_dimension=3,
        )

        self.assertEqual(state, {"records": []})
