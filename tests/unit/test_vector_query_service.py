"""Unit tests for Pinecone vector queries."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.clients.pinecone_client import PineconeClientError
from app.clients.pinecone_dtos import PineconeQueryMatchDTO, PineconeQueryResponseDTO
from app.config.defaults import PineconeConfig
from app.services.vector_preparation_service import VectorDimensionError
from app.services.vector_query_service import VectorQueryError, query_pinecone_vectors


@dataclass(frozen=True, slots=True)
class FakeQueryResponse:
    """In-memory Pinecone query response."""

    matches: tuple[object, ...]
    namespace: str | None = None


class FakePineconeClient:
    """In-memory Pinecone client for offline query tests."""

    def __init__(self, response: object) -> None:
        self._response = response
        self.query_calls: list[dict[str, object]] = []

    def query(self, vector, namespace, top_k, filter=None):  # noqa: ANN001
        self.query_calls.append({"vector": tuple(vector), "namespace": namespace, "top_k": top_k, "filter": filter})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def upsert(self, records, namespace):  # noqa: ANN001
        raise AssertionError("upsert should not be called during query tests.")

    def delete(self, namespace, ids=None, filter=None, delete_all=False):  # noqa: ANN001
        raise AssertionError("delete should not be called during query tests.")


class VectorQueryServiceTests(unittest.TestCase):
    """Offline tests for Pinecone vector queries."""

    def _build_config(self, vector_dimension: int = 3, max_query_top_k: int = 5) -> PineconeConfig:
        return PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=vector_dimension,
            api_version="2024-07",
            max_upsert_batch_size=100,
            max_query_top_k=max_query_top_k,
        )

    def test_valid_query_vector_returns_sorted_matches(self) -> None:
        response = PineconeQueryResponseDTO(
            matches=(
                PineconeQueryMatchDTO(record_id="vec-b", score=0.9, metadata={"source_id": "source-b"}),
                PineconeQueryMatchDTO(record_id="vec-a", score=0.9, metadata={"source_id": "source-a"}),
                PineconeQueryMatchDTO(record_id="vec-c", score=0.1, metadata={"source_id": "source-c"}),
            ),
            namespace="company:cik:abc",
        )
        client = FakePineconeClient(response)

        result = query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config(), top_k=4)

        self.assertIsInstance(result, PineconeQueryResponseDTO)
        self.assertEqual([match.record_id for match in result.matches], ["vec-a", "vec-b", "vec-c"])
        self.assertEqual(len(client.query_calls), 1)

    def test_top_k_is_bounded(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config(max_query_top_k=5), top_k=999)

        self.assertEqual(client.query_calls[0]["top_k"], 5)

    def test_namespace_is_required(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, 0.2, 0.3), client, " ", self._build_config())

    def test_dimension_mismatch_rejected(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        with self.assertRaises(VectorDimensionError):
            query_pinecone_vectors((0.1, 0.2), client, "company:cik:abc", self._build_config())

    def test_invalid_vector_values_rejected(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, float("nan"), 0.3), client, "company:cik:abc", self._build_config())

    def test_filter_validation(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config(), filter={})

    def test_invalid_filter_value_rejected(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config(), filter={"bad": object()})

    def test_duplicate_match_ids_rejected(self) -> None:
        client = FakePineconeClient(
            FakeQueryResponse(
                matches=(
                    PineconeQueryMatchDTO(record_id="vec-1", score=0.9),
                    PineconeQueryMatchDTO(record_id="vec-1", score=0.8),
                ),
                namespace="company:cik:abc",
            )
        )

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config())

    def test_valid_zero_match_response(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        result = query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config())

        self.assertEqual(result.matches, ())

    def test_invalid_top_k_rejected(self) -> None:
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        for invalid_top_k in (0, -1):
            with self.subTest(invalid_top_k=invalid_top_k):
                with self.assertRaises(VectorQueryError):
                    query_pinecone_vectors(
                        (0.1, 0.2, 0.3),
                        client,
                        "company:cik:abc",
                        self._build_config(),
                        top_k=invalid_top_k,
                    )

    def test_client_errors_propagate_as_typed_service_errors(self) -> None:
        client = FakePineconeClient(PineconeClientError("rate limited"))

        with self.assertRaises(VectorQueryError):
            query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config())

    def test_no_shared_state_mutation(self) -> None:
        state = {"matches": []}
        response = PineconeQueryResponseDTO(matches=(), namespace="company:cik:abc")
        client = FakePineconeClient(response)

        query_pinecone_vectors((0.1, 0.2, 0.3), client, "company:cik:abc", self._build_config())

        self.assertEqual(state, {"matches": []})
