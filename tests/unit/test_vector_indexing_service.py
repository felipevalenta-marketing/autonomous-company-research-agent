"""Unit tests for Pinecone indexing and deletion."""

from __future__ import annotations

import unittest

from app.clients.pinecone_client import PineconeClientError, PineconeDeleteResultDTO, PineconeUpsertResultDTO
from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.services.vector_indexing_service import (
    VectorBatchError,
    VectorDeletionError,
    VectorIndexingError,
    VectorIndexingResult,
    delete_pinecone_vectors,
    index_pinecone_vectors,
)


class FakePineconeClient:
    """In-memory Pinecone client for offline indexing tests."""

    def __init__(self, upsert_responses: tuple[object, ...], delete_response: object) -> None:
        self._upsert_responses = list(upsert_responses)
        self._delete_response = delete_response
        self.upsert_calls: list[tuple[tuple[PineconeVectorRecordDTO, ...], str]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.query_calls: list[object] = []

    def upsert(self, records, namespace):  # noqa: ANN001
        batch = tuple(records)
        self.upsert_calls.append((batch, namespace))
        if not self._upsert_responses:
            raise AssertionError("No fake upsert response configured.")
        response = self._upsert_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def delete(self, namespace, ids=None, filter=None, delete_all=False):  # noqa: ANN001
        self.delete_calls.append({"namespace": namespace, "ids": ids, "filter": filter, "delete_all": delete_all})
        response = self._delete_response
        if isinstance(response, Exception):
            raise response
        return response

    def query(self, vector, namespace, top_k, filter=None):  # noqa: ANN001
        self.query_calls.append((vector, namespace, top_k, filter))
        raise AssertionError("query should not be called during indexing tests.")


class VectorIndexingServiceTests(unittest.TestCase):
    """Offline tests for deterministic Pinecone indexing."""

    def _build_records(self) -> tuple[PineconeVectorRecordDTO, ...]:
        return (
            PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3), metadata={"source_id": "source-1"}),
            PineconeVectorRecordDTO(record_id="vec-2", values=(0.4, 0.5, 0.6), metadata={"source_id": "source-2"}),
            PineconeVectorRecordDTO(record_id="vec-3", values=(0.7, 0.8, 0.9), metadata={"source_id": "source-3"}),
        )

    def _build_config(self, max_upsert_batch_size: int = 2) -> PineconeConfig:
        return PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=3,
            api_version="2024-07",
            max_upsert_batch_size=max_upsert_batch_size,
            max_query_top_k=10,
        )

    def test_deterministic_batches_preserve_order(self) -> None:
        client = FakePineconeClient(
            (
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=2),
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=1),
            ),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )

        result = index_pinecone_vectors(self._build_records(), client, "company:cik:abc", self._build_config())

        self.assertIsInstance(result, VectorIndexingResult)
        self.assertEqual(result.namespace, "company:cik:abc")
        self.assertEqual(result.attempted_count, 3)
        self.assertEqual(result.accepted_count, 3)
        self.assertEqual(len(client.upsert_calls), 2)
        self.assertEqual([len(batch) for batch, _ in client.upsert_calls], [2, 1])
        self.assertEqual([batch[0].record_id for batch, _ in client.upsert_calls], ["vec-1", "vec-3"])
        self.assertEqual(len(client.query_calls), 0)

    def test_batch_size_one(self) -> None:
        client = FakePineconeClient(
            (
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=1),
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=1),
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=1),
            ),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )

        index_pinecone_vectors(self._build_records(), client, "company:cik:abc", self._build_config(), batch_size=1)

        self.assertEqual(len(client.upsert_calls), 3)

    def test_exact_batch_size(self) -> None:
        client = FakePineconeClient(
            (PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=2),),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )
        records = self._build_records()[:2]

        index_pinecone_vectors(records, client, "company:cik:abc", self._build_config(max_upsert_batch_size=2))

        self.assertEqual(len(client.upsert_calls), 1)

    def test_final_partial_batch(self) -> None:
        client = FakePineconeClient(
            (
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=2),
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=1),
            ),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )

        index_pinecone_vectors(self._build_records(), client, "company:cik:abc", self._build_config(max_upsert_batch_size=2))

        self.assertEqual(len(client.upsert_calls), 2)

    def test_invalid_batch_size_rejected(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0))

        for invalid_batch_size in (0, -1):
            with self.subTest(invalid_batch_size=invalid_batch_size):
                with self.assertRaises(VectorBatchError):
                    index_pinecone_vectors(
                        self._build_records(),
                        client,
                        "company:cik:abc",
                        self._build_config(),
                        batch_size=invalid_batch_size,
                    )

    def test_failed_batch_raises_typed_error(self) -> None:
        client = FakePineconeClient(
            (
                PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=2),
                PineconeClientError("boom"),
            ),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )

        with self.assertRaises(VectorBatchError):
            index_pinecone_vectors(self._build_records(), client, "company:cik:abc", self._build_config())

        self.assertEqual(len(client.upsert_calls), 2)

    def test_delete_explicit_ids(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=2))
        result = delete_pinecone_vectors(client, "company:cik:abc", ids=("vec-1", "vec-2"))

        self.assertEqual(result.deleted_count, 2)
        self.assertEqual(client.delete_calls[0]["ids"], ("vec-1", "vec-2"))
        self.assertEqual(client.query_calls, [])

    def test_delete_by_filter(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=1))
        result = delete_pinecone_vectors(client, "company:cik:abc", filter={"source_id": "source-1"})

        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(client.delete_calls[0]["filter"], {"source_id": "source-1"})

    def test_delete_all(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=3))
        result = delete_pinecone_vectors(client, "company:cik:abc", delete_all=True)

        self.assertEqual(result.deleted_count, 3)
        self.assertTrue(client.delete_calls[0]["delete_all"])
        self.assertEqual(client.query_calls, [])

    def test_ambiguous_delete_request_rejected(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0))

        with self.assertRaises(VectorDeletionError):
            delete_pinecone_vectors(client, "company:cik:abc", ids=("vec-1",), delete_all=True)

    def test_empty_ids_do_not_become_delete_all(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0))

        with self.assertRaises(VectorDeletionError):
            delete_pinecone_vectors(client, "company:cik:abc", ids=())

    def test_namespace_is_required(self) -> None:
        client = FakePineconeClient((), PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0))

        with self.assertRaises(VectorIndexingError):
            index_pinecone_vectors(self._build_records(), client, " ", self._build_config())

    def test_no_shared_state_mutation(self) -> None:
        state = {"records": []}
        client = FakePineconeClient(
            (PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=3),),
            PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=0),
        )

        index_pinecone_vectors(self._build_records(), client, "company:cik:abc", self._build_config(max_upsert_batch_size=3))

        self.assertEqual(state, {"records": []})
