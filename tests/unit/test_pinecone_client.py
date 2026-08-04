"""Unit tests for the Pinecone client."""

from __future__ import annotations

import json
import unittest

import httpx

from app.clients.pinecone_client import (
    PineconeAuthenticationError,
    PineconeClient,
    PineconeConfigurationError,
    PineconePayloadError,
    PineconeRateLimitError,
    PineconeResponseValidationError,
    PineconeTimeoutError,
    PineconeTransportError,
)
from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.models.execution import RuntimeConfig


class PineconeClientTests(unittest.TestCase):
    """Offline tests for Pinecone transport and validation."""

    def _build_client(
        self,
        handler,
        *,
        api_key: str | None = "pinecone-key",
        index_host: str | None = "https://example-index.svc.pinecone.io",
        api_version: str | None = "2024-07",
        max_retries: int = 0,
        timeout_seconds: float = 1.0,
        vector_dimension: int = 3,
        max_upsert_batch_size: int = 100,
        max_query_top_k: int = 10,
    ) -> PineconeClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(max_retries=max_retries, timeout_seconds=timeout_seconds)
        pinecone_config = PineconeConfig(
            api_key=api_key,
            index_host=index_host,
            namespace_prefix="company",
            vector_dimension=vector_dimension,
            api_version=api_version,
            max_upsert_batch_size=max_upsert_batch_size,
            max_query_top_k=max_query_top_k,
        )
        return PineconeClient(runtime_config=runtime_config, pinecone_config=pinecone_config, http_client=http_client)

    def test_successful_upsert_maps_to_dto(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/vectors/upsert")
            self.assertEqual(request.headers["Api-Key"], "pinecone-key")
            self.assertEqual(request.headers["X-Pinecone-API-Version"], "2024-07")
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["namespace"], "company:cik:abc")
            self.assertEqual(len(body["vectors"]), 2)
            self.assertEqual(body["vectors"][0]["id"], "vec-1")
            self.assertEqual(body["vectors"][0]["values"], [0.1, 0.2, 0.3])
            self.assertEqual(body["vectors"][0]["metadata"]["source_id"], "source-1")
            self.assertNotIn("api_key", body)
            return httpx.Response(200, json={"upsertedCount": 2})

        client = self._build_client(handler)
        response = client.upsert(
            (
                PineconeVectorRecordDTO(
                    record_id="vec-1",
                    values=(0.1, 0.2, 0.3),
                    metadata={"source_id": "source-1"},
                ),
                PineconeVectorRecordDTO(
                    record_id="vec-2",
                    values=(0.4, 0.5, 0.6),
                    metadata={"source_id": "source-2"},
                ),
            ),
            "company:cik:abc",
        )

        self.assertEqual(response.namespace, "company:cik:abc")
        self.assertEqual(response.upserted_count, 2)
        self.assertEqual(len(captured), 1)

    def test_successful_query_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/query")
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["vector"], [0.1, 0.2, 0.3])
            self.assertEqual(body["topK"], 4)
            self.assertEqual(body["namespace"], "company:cik:abc")
            self.assertTrue(body["includeMetadata"])
            self.assertNotIn("api_key", body)
            return httpx.Response(
                200,
                json={
                    "matches": [
                        {"id": "vec-1", "score": 0.2, "metadata": {"source_id": "source-1"}},
                        {"id": "vec-2", "score": 0.1, "metadata": {"source_id": "source-2"}},
                    ],
                    "namespace": "company:cik:abc",
                },
            )

        client = self._build_client(handler)
        response = client.query((0.1, 0.2, 0.3), "company:cik:abc", 4)

        self.assertEqual(response.namespace, "company:cik:abc")
        self.assertEqual([match.record_id for match in response.matches], ["vec-1", "vec-2"])

    def test_successful_query_with_empty_values_treats_values_as_absent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/query")
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["namespace"], "company:cik:abc")
            return httpx.Response(
                200,
                json={
                    "matches": [
                        {
                            "id": "vec-1",
                            "score": 0.2,
                            "metadata": {"source_id": "source-1"},
                            "values": [],
                        }
                    ],
                    "namespace": "company:cik:abc",
                },
            )

        client = self._build_client(handler)
        response = client.query((0.1, 0.2, 0.3), "company:cik:abc", 4)

        self.assertEqual(response.namespace, "company:cik:abc")
        self.assertIsNone(response.matches[0].values)

    def test_delete_by_ids_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/vectors/delete")
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["namespace"], "company:cik:abc")
            self.assertEqual(body["ids"], ["vec-1", "vec-2"])
            self.assertNotIn("deleteAll", body)
            return httpx.Response(200, json={"deletedCount": 2})

        client = self._build_client(handler)
        response = client.delete("company:cik:abc", ids=("vec-1", "vec-2"))

        self.assertEqual(response.namespace, "company:cik:abc")
        self.assertEqual(response.deleted_count, 2)

    def test_delete_by_filter_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["namespace"], "company:cik:abc")
            self.assertEqual(body["filter"], {"source_id": "source-1"})
            return httpx.Response(200, json={"deletedCount": 1})

        client = self._build_client(handler)
        response = client.delete("company:cik:abc", filter={"source_id": "source-1"})

        self.assertEqual(response.deleted_count, 1)

    def test_delete_all_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            self.assertTrue(body["deleteAll"])
            self.assertEqual(body["namespace"], "company:cik:abc")
            return httpx.Response(200, json={"deletedCount": 3})

        client = self._build_client(handler)
        response = client.delete("company:cik:abc", delete_all=True)

        self.assertEqual(response.deleted_count, 3)

    def test_ambiguous_delete_request_rejected(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"deletedCount": 0}))

        with self.assertRaises(PineconePayloadError):
            client.delete("company:cik:abc", ids=("vec-1",), delete_all=True)

    def test_missing_api_key_raises_configuration_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"upsertedCount": 1}), api_key=None)

        with self.assertRaises(PineconeConfigurationError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_missing_host_raises_configuration_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"upsertedCount": 1}), index_host=None)

        with self.assertRaises(PineconeConfigurationError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_host_with_path_or_query_raises_configuration_error(self) -> None:
        client = self._build_client(
            lambda request: httpx.Response(200, json={"upsertedCount": 1}),
            index_host="https://example-index.svc.pinecone.io/unsafe?query=1",
        )

        with self.assertRaises(PineconeConfigurationError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_http_401_raises_authentication_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(401, text="unauthorized"))

        with self.assertRaises(PineconeAuthenticationError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_http_400_raises_payload_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(400, text="bad request"))

        with self.assertRaises(PineconePayloadError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_http_429_raises_rate_limit_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(429, text="rate limited"))

        with self.assertRaises(PineconeRateLimitError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(PineconeTimeoutError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_http_5xx_raises_transport_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(500, text="server error"))

        with self.assertRaises(PineconeTransportError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_malformed_json_raises_validation_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, text="{not-json"))

        with self.assertRaises(PineconeResponseValidationError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_malformed_successful_payload_raises_payload_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"unexpected": 1}))

        with self.assertRaises(PineconePayloadError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

    def test_upsert_dimension_mismatch_raises_payload_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"upsertedCount": 1}))

        with self.assertRaises(PineconePayloadError):
            client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2)),), "company:cik:abc")

    def test_query_dimension_mismatch_raises_payload_error(self) -> None:
        client = self._build_client(lambda request: httpx.Response(200, json={"matches": []}))

        with self.assertRaises(PineconePayloadError):
            client.query((0.1, 0.2), "company:cik:abc", 4)

    def test_api_key_is_not_present_in_url_or_metadata(self) -> None:
        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"upsertedCount": 1})

        client = self._build_client(handler)
        client.upsert((PineconeVectorRecordDTO(record_id="vec-1", values=(0.1, 0.2, 0.3)),), "company:cik:abc")

        request = captured_requests[0]
        body = json.loads(request.content.decode("utf-8"))
        self.assertNotIn("api_key", body)
        self.assertNotIn("apikey", request.url.params)
        self.assertEqual(request.headers["Api-Key"], "pinecone-key")

    def test_exception_messages_do_not_leak_vectors(self) -> None:
        client = self._build_client(lambda request: httpx.Response(500, text="server error"))
        vector = (0.1, 0.2, 0.3)

        with self.assertRaises(PineconeTransportError) as context:
            client.query(vector, "company:cik:abc", 4)

        self.assertNotIn(str(vector), str(context.exception))
