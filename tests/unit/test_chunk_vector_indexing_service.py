"""Unit tests for chunk vector indexing orchestration."""

from __future__ import annotations

import unittest

from app.clients.pinecone_client import PineconeClientProtocol
from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.services.chunk_vector_indexing_service import (
    ChunkVectorIndexingError,
    ChunkVectorIndexingInputError,
    index_chunk_vectors,
)
from app.services.vector_indexing_service import VectorBatchError, VectorIndexingResult


class CapturingVectorIndexingService:
    """In-memory indexing dependency for offline orchestration tests."""

    def __init__(self, response: object | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[tuple[tuple[PineconeVectorRecordDTO, ...], PineconeClientProtocol, str, PineconeConfig, int | None]] = []

    def __call__(
        self,
        records,
        pinecone_client,  # noqa: ANN001
        namespace,  # noqa: ANN001
        pinecone_config,  # noqa: ANN001
        *,
        batch_size: int | None = None,
    ) -> object:
        batch = tuple(records)
        self.calls.append((batch, pinecone_client, namespace, pinecone_config, batch_size))
        if self.exc is not None:
            raise self.exc
        if self.response is not None:
            return self.response
        return VectorIndexingResult(
            namespace=namespace,
            attempted_count=len(batch),
            accepted_count=len(batch),
            acknowledgements=(),
        )


def _build_record(
    *,
    record_id: str,
    values: tuple[float, ...] = (0.1, 0.2, 0.3),
    metadata: dict[str, object] | None = None,
) -> PineconeVectorRecordDTO:
    return PineconeVectorRecordDTO(
        record_id=record_id,
        values=values,
        metadata=metadata or {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "source_id": "source-1",
            "company_name": "Example Corp",
            "text_id": "alpha beta gamma",
            "content_checksum": "checksum-1",
            "filing_form": "10-K",
            "source_url": "https://example.com/doc",
            "filing_date": "2024-01-01",
        },
    )


def _build_config() -> PineconeConfig:
    return PineconeConfig(
        api_key="pinecone-key",
        index_host="https://example-index.svc.pinecone.io",
        namespace_prefix="company",
        vector_dimension=3,
        api_version="2024-07",
        max_upsert_batch_size=2,
        max_query_top_k=10,
    )


class ChunkVectorIndexingServiceTests(unittest.TestCase):
    """Offline tests for deterministic chunk vector indexing."""

    def test_valid_prepared_vectors_delegate_once_and_preserve_order(self) -> None:
        records = (
            _build_record(record_id="vec-1"),
            _build_record(record_id="vec-2", values=(0.4, 0.5, 0.6)),
        )
        dependency = CapturingVectorIndexingService()
        client = object()

        result = index_chunk_vectors(
            records,
            client,  # type: ignore[arg-type]
            "company:cik:abc",
            _build_config(),
            batch_size=1,
            vector_indexing_service=dependency,
        )

        self.assertEqual(len(dependency.calls), 1)
        call_records, call_client, call_namespace, call_config, call_batch_size = dependency.calls[0]
        self.assertEqual(call_records, records)
        self.assertIs(call_client, client)
        self.assertEqual(call_namespace, "company:cik:abc")
        self.assertEqual(call_config.namespace_prefix, "company")
        self.assertEqual(call_batch_size, 1)
        self.assertIsInstance(result, VectorIndexingResult)
        self.assertEqual(result.namespace, "company:cik:abc")
        self.assertEqual(result.attempted_count, 2)
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(records[0].record_id, "vec-1")
        self.assertEqual(records[1].record_id, "vec-2")

    def test_empty_tuple_returns_empty_result_without_call(self) -> None:
        dependency = CapturingVectorIndexingService()

        result = index_chunk_vectors(
            (),
            object(),  # type: ignore[arg-type]
            "company:cik:abc",
            _build_config(),
            vector_indexing_service=dependency,
        )

        self.assertEqual(result.namespace, "company:cik:abc")
        self.assertEqual(result.attempted_count, 0)
        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.acknowledgements, ())
        self.assertEqual(dependency.calls, [])

    def test_wrong_collection_type_rejected(self) -> None:
        dependency = CapturingVectorIndexingService()

        with self.assertRaises(ChunkVectorIndexingInputError):
            index_chunk_vectors(  # type: ignore[arg-type]
                [_build_record(record_id="vec-1")],
                object(),  # type: ignore[arg-type]
                "company:cik:abc",
                _build_config(),
                vector_indexing_service=dependency,
            )

    def test_invalid_element_rejected(self) -> None:
        dependency = CapturingVectorIndexingService()

        with self.assertRaises(ChunkVectorIndexingInputError):
            index_chunk_vectors(
                (_build_record(record_id="vec-1"), object()),  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
                "company:cik:abc",
                _build_config(),
                vector_indexing_service=dependency,
            )

    def test_duplicate_vector_id_rejected(self) -> None:
        dependency = CapturingVectorIndexingService()
        first = _build_record(record_id="vec-1")
        second = _build_record(record_id="vec-1", values=(0.4, 0.5, 0.6))

        with self.assertRaises(ChunkVectorIndexingInputError):
            index_chunk_vectors((first, second), object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

    def test_input_tuple_remains_unchanged(self) -> None:
        records = (_build_record(record_id="vec-1"),)
        snapshot = records
        dependency = CapturingVectorIndexingService()

        index_chunk_vectors(records, object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

        self.assertIs(records, snapshot)
        self.assertEqual(records[0].record_id, "vec-1")

    def test_metadata_vector_and_namespace_are_preserved(self) -> None:
        records = (
            _build_record(record_id="vec-1", values=(0.1, 0.2, 0.3)),
            _build_record(record_id="vec-2", values=(0.4, 0.5, 0.6), metadata={
                "chunk_id": "chunk-2",
                "document_id": "doc-2",
                "source_id": "source-2",
                "company_name": "Example Corp",
                "text_id": "gamma delta",
                "content_checksum": "checksum-2",
                "filing_form": "10-Q",
                "source_url": "https://example.com/doc-2",
                "filing_date": "2024-02-01",
            }),
        )
        dependency = CapturingVectorIndexingService()

        index_chunk_vectors(records, object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

        call_records, _, call_namespace, _, _ = dependency.calls[0]
        self.assertEqual(call_namespace, "company:cik:abc")
        self.assertEqual(call_records, records)
        self.assertEqual([record.values for record in call_records], [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)])
        self.assertEqual([record.metadata["chunk_id"] for record in call_records], ["chunk-1", "chunk-2"])
        self.assertNotIn("vectors", call_records[0].metadata)

    def test_repeated_calls_are_deterministic(self) -> None:
        records = (_build_record(record_id="vec-1"),)
        dependency = CapturingVectorIndexingService()

        client = object()
        first = index_chunk_vectors(records, client, "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]
        second = index_chunk_vectors(records, client, "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

        self.assertEqual(first, second)
        self.assertEqual(len(dependency.calls), 2)
        first_call = dependency.calls[0]
        second_call = dependency.calls[1]
        self.assertEqual(first_call[0], second_call[0])
        self.assertEqual(first_call[2:], second_call[2:])

    def test_no_hidden_accumulation(self) -> None:
        records = (_build_record(record_id="vec-1"),)
        dependency = CapturingVectorIndexingService()

        index_chunk_vectors(records, object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]
        index_chunk_vectors(records, object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

        self.assertEqual(len(dependency.calls), 2)

    def test_downstream_indexing_error_propagates(self) -> None:
        dependency = CapturingVectorIndexingService(exc=VectorBatchError("boom"))

        with self.assertRaises(VectorBatchError):
            index_chunk_vectors((_build_record(record_id="vec-1"),), object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

    def test_invalid_dependency_result_is_wrapped(self) -> None:
        dependency = CapturingVectorIndexingService(response="bad-result")

        with self.assertRaises(ChunkVectorIndexingError):
            index_chunk_vectors((_build_record(record_id="vec-1"),), object(), "company:cik:abc", _build_config(), vector_indexing_service=dependency)  # type: ignore[arg-type]

    def test_no_forbidden_imports_in_source(self) -> None:
        with open("app/services/chunk_vector_indexing_service.py", encoding="utf-8") as handle:
            source = handle.read()

        for forbidden in (
            "from pinecone",
            "import pinecone",
            "Pinecone(",
            "Index(",
            "os.environ",
            "os.getenv",
            "langgraph",
            "app.models.state",
            "app.rag",
            "report",
            "exporter",
            "n8n",
        ):
            self.assertNotIn(forbidden, source)
