"""Unit tests for chunk vector preparation orchestration."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.models.company import ResolvedCompany
from app.models.chunks import ChunkRecord
from app.services.chunk_embedding_service import EmbeddedChunkRecord
from app.services.chunk_vector_preparation_service import (
    ChunkVectorPreparationError,
    ChunkVectorPreparationInputError,
    ChunkVectorPreparationMappingError,
    prepare_chunk_vectors,
)
from app.services.embedding_service import EmbeddingRecord
from app.services.vector_preparation_service import (
    VectorMetadataError,
    build_pinecone_namespace,
    prepare_pinecone_vectors,
)
from app.utils.hashing import sha256_text


class CapturingVectorPreparationService:
    """In-memory vector-preparation dependency for offline orchestration tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[str, ...], tuple[dict[str, object], ...], int | None]] = []

    def __call__(
        self,
        embedding_result,
        record_identities,  # noqa: ANN001
        metadata_entries,  # noqa: ANN001
        *,
        expected_dimension: int | None = None,
    ) -> tuple[PineconeVectorRecordDTO, ...]:
        records = prepare_pinecone_vectors(
            embedding_result,
            record_identities,
            metadata_entries,
            expected_dimension=expected_dimension,
        )
        self.calls.append((embedding_result, tuple(record_identities), tuple(metadata_entries), expected_dimension))
        return records


def _build_chunk(
    *,
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    source_id: str = "source-1",
    company_name: str = "Example Corp",
    document_type: str = "10-K",
    text: str = "alpha beta gamma",
    source_url: str | None = "https://example.com/doc",
    filing_date: str | None = "2024-01-01",
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        source_id=source_id,
        company_name=company_name,
        chunk_index=0,
        text=text,
        start_offset=0,
        end_offset=len(text),
        content_checksum=sha256_text(text),
        document_type=document_type,
        source_url=source_url,
        filing_type="10-K",
        filing_date=filing_date,
        fiscal_period="FY2024",
    )


def _build_embedding(
    *,
    input_index: int,
    text: str,
    model: str = "text-embedding-3-small",
    vector: tuple[float, ...] = (0.1, 0.2, 0.3),
) -> EmbeddingRecord:
    return EmbeddingRecord(
        input_index=input_index,
        input_checksum=sha256_text(text),
        model=model,
        vector_dimension=len(vector),
        vector=vector,
    )


def _build_embedded_chunk(
    *,
    chunk_id: str = "chunk-1",
    input_index: int = 0,
    text: str = "alpha beta gamma",
    vector: tuple[float, ...] = (0.1, 0.2, 0.3),
    chunk_kwargs: dict[str, object] | None = None,
) -> EmbeddedChunkRecord:
    chunk = _build_chunk(chunk_id=chunk_id, text=text, **(chunk_kwargs or {}))
    chunk = replace(chunk, chunk_index=input_index, end_offset=len(text))
    embedding = _build_embedding(input_index=input_index, text=text, vector=vector)
    return EmbeddedChunkRecord(chunk=chunk, embedding=embedding)


class ChunkVectorPreparationServiceTests(unittest.TestCase):
    """Offline tests for deterministic chunk vector preparation."""

    def test_valid_tuple_prepares_vectors_and_preserves_order(self) -> None:
        embedded_chunks = (
            _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta"),
            _build_embedded_chunk(chunk_id="chunk-2", input_index=1, text="gamma delta", vector=(0.4, 0.5, 0.6)),
        )
        dependency = CapturingVectorPreparationService()

        prepared = prepare_chunk_vectors(embedded_chunks, vector_preparation_service=dependency)

        self.assertEqual(len(dependency.calls), 1)
        self.assertEqual([record.record_id for record in prepared], [record.record_id for record in prepared])
        self.assertEqual([record.metadata["chunk_id"] for record in prepared], ["chunk-1", "chunk-2"])
        self.assertEqual([record.values for record in prepared], [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)])
        self.assertEqual([record.metadata["text_id"] for record in prepared], ["alpha beta", "gamma delta"])

    def test_empty_tuple_returns_empty_tuple_without_call(self) -> None:
        dependency = CapturingVectorPreparationService()

        prepared = prepare_chunk_vectors((), vector_preparation_service=dependency)

        self.assertEqual(prepared, ())
        self.assertEqual(dependency.calls, [])

    def test_wrong_collection_type_rejected(self) -> None:
        dependency = CapturingVectorPreparationService()

        with self.assertRaises(ChunkVectorPreparationInputError):
            prepare_chunk_vectors([_build_embedded_chunk()], vector_preparation_service=dependency)  # type: ignore[arg-type]

    def test_invalid_element_rejected(self) -> None:
        dependency = CapturingVectorPreparationService()

        with self.assertRaises(ChunkVectorPreparationInputError):
            prepare_chunk_vectors((_build_embedded_chunk(), object()), vector_preparation_service=dependency)  # type: ignore[arg-type]

    def test_duplicate_chunk_id_rejected(self) -> None:
        first = _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta")
        second = _build_embedded_chunk(chunk_id="chunk-1", input_index=1, text="gamma delta", vector=(0.4, 0.5, 0.6))
        dependency = CapturingVectorPreparationService()

        with self.assertRaises(ChunkVectorPreparationInputError):
            prepare_chunk_vectors((first, second), vector_preparation_service=dependency)

    def test_duplicate_embedding_index_rejected(self) -> None:
        first = _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta")
        second = _build_embedded_chunk(chunk_id="chunk-2", input_index=1, text="gamma delta", vector=(0.4, 0.5, 0.6))
        object.__setattr__(second.embedding, "input_index", 0)
        dependency = CapturingVectorPreparationService()

        with self.assertRaises(ChunkVectorPreparationInputError):
            prepare_chunk_vectors((first, second), vector_preparation_service=dependency)

    def test_invalid_vector_rejected(self) -> None:
        embedded = _build_embedded_chunk()
        object.__setattr__(embedded.embedding, "vector", ())
        object.__setattr__(embedded.embedding, "vector_dimension", 0)
        dependency = CapturingVectorPreparationService()

        with self.assertRaises(ChunkVectorPreparationInputError):
            prepare_chunk_vectors((embedded,), vector_preparation_service=dependency)

    def test_input_tuple_remains_unchanged(self) -> None:
        embedded = _build_embedded_chunk()
        chunks = (embedded,)
        snapshot = chunks
        dependency = CapturingVectorPreparationService()

        prepare_chunk_vectors(chunks, vector_preparation_service=dependency)

        self.assertIs(chunks, snapshot)
        self.assertEqual(chunks[0].chunk.chunk_id, "chunk-1")

    def test_one_output_per_input_and_metadata_preserved(self) -> None:
        embedded_chunks = (
            _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta"),
            _build_embedded_chunk(chunk_id="chunk-2", input_index=1, text="gamma delta", vector=(0.4, 0.5, 0.6)),
        )
        dependency = CapturingVectorPreparationService()

        prepared = prepare_chunk_vectors(embedded_chunks, vector_preparation_service=dependency)

        self.assertEqual(len(prepared), 2)
        self.assertEqual([record.metadata["chunk_id"] for record in prepared], ["chunk-1", "chunk-2"])
        self.assertEqual([record.metadata["document_id"] for record in prepared], ["doc-1", "doc-1"])
        self.assertEqual([record.metadata["source_id"] for record in prepared], ["source-1", "source-1"])
        self.assertEqual([record.metadata["company_name"] for record in prepared], ["Example Corp", "Example Corp"])
        self.assertEqual([record.metadata["filing_form"] for record in prepared], ["10-K", "10-K"])
        self.assertEqual([record.metadata["source_url"] for record in prepared], ["https://example.com/doc", "https://example.com/doc"])
        self.assertEqual([record.metadata["filing_date"] for record in prepared], ["2024-01-01", "2024-01-01"])
        self.assertNotIn("vectors", prepared[0].metadata)
        self.assertNotIn("ticker", prepared[0].metadata)
        self.assertNotIn("cik", prepared[0].metadata)
        self.assertNotIn("fiscal_period", prepared[0].metadata)

    def test_repeated_calls_are_deterministic(self) -> None:
        embedded_chunks = (
            _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta"),
            _build_embedded_chunk(chunk_id="chunk-2", input_index=1, text="gamma delta", vector=(0.4, 0.5, 0.6)),
        )
        first = prepare_chunk_vectors(embedded_chunks)
        second = prepare_chunk_vectors(embedded_chunks)

        self.assertEqual(first, second)
        self.assertEqual([record.record_id for record in first], [record.record_id for record in second])

    def test_no_hidden_accumulation(self) -> None:
        embedded = _build_embedded_chunk()
        first = prepare_chunk_vectors((embedded,))
        second = prepare_chunk_vectors((embedded,))

        self.assertEqual(first, second)

    def test_namespace_helper_is_deterministic_and_prefers_cik(self) -> None:
        cik_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Example Corp", ticker="EXM", cik="0000123456"),
            "company",
        )
        ticker_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Example Corp", ticker="EXM"),
            "company",
        )
        company_namespace = build_pinecone_namespace(
            ResolvedCompany(company_name="Example Corp"),
            "company",
        )

        self.assertEqual(
            cik_namespace,
            build_pinecone_namespace(ResolvedCompany(company_name="Example Corp", ticker="EXM", cik="0000123456"), "company"),
        )
        self.assertNotEqual(cik_namespace, ticker_namespace)
        self.assertNotEqual(ticker_namespace, company_namespace)

    def test_chunk_identity_is_preserved(self) -> None:
        embedded = _build_embedded_chunk(chunk_id="chunk-1", input_index=0, text="alpha beta")

        prepared = prepare_chunk_vectors((embedded,))

        self.assertEqual(prepared[0].record_id, prepared[0].record_id)
        self.assertEqual(prepared[0].metadata["chunk_id"], embedded.chunk.chunk_id)

    def test_vector_is_preserved_exactly(self) -> None:
        embedded = _build_embedded_chunk(vector=(0.7, 0.8, 0.9))

        prepared = prepare_chunk_vectors((embedded,))

        self.assertEqual(prepared[0].values, (0.7, 0.8, 0.9))

    def test_preparation_failure_is_wrapped(self) -> None:
        class ErrorService:
            def __call__(self, embedding_result, record_identities, metadata_entries, *, expected_dimension=None):  # noqa: ANN001
                raise RuntimeError("boom")

        with self.assertRaises(ChunkVectorPreparationError):
            prepare_chunk_vectors((_build_embedded_chunk(),), vector_preparation_service=ErrorService())

    def test_existing_vector_preparation_error_is_mapped(self) -> None:
        class ErrorService:
            def __call__(self, embedding_result, record_identities, metadata_entries, *, expected_dimension=None):  # noqa: ANN001
                raise VectorMetadataError("boom")

        with self.assertRaises(ChunkVectorPreparationMappingError):
            prepare_chunk_vectors((_build_embedded_chunk(),), vector_preparation_service=ErrorService())

    def test_no_forbidden_imports_in_source(self) -> None:
        with open("app/services/chunk_vector_preparation_service.py", encoding="utf-8") as handle:
            source = handle.read()

        for forbidden in ("PineconeClient(", "vector_indexing_service", "langgraph", "app.models.state", "app.rag", "report", "prompts", "exporters", "n8n"):
            self.assertNotIn(forbidden, source)
