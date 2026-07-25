"""Unit tests for the OpenAI embeddings client."""

from __future__ import annotations

import json
import unittest

import httpx

from app.clients.openai_embeddings_client import (
    OpenAIEmbeddingsAuthenticationError,
    OpenAIEmbeddingsClient,
    OpenAIEmbeddingsConfigurationError,
    OpenAIEmbeddingsPayloadError,
    OpenAIEmbeddingsRateLimitError,
    OpenAIEmbeddingsResponseValidationError,
    OpenAIEmbeddingsTimeoutError,
    OpenAIEmbeddingsTransportError,
)
from app.config.constants import OPENAI_BASE_URL, OPENAI_DEFAULT_EMBEDDING_MODEL
from app.models.execution import RuntimeConfig


class OpenAIEmbeddingsClientTests(unittest.TestCase):
    """Offline tests for OpenAI embeddings transport and validation."""

    def _build_client(
        self,
        handler,
        *,
        api_key: str | None = "demo",
        max_retries: int = 0,
        timeout_seconds: float = 1.0,
        base_url: str = OPENAI_BASE_URL,
        default_model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    ) -> OpenAIEmbeddingsClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(openai_api_key=api_key, max_retries=max_retries, timeout_seconds=timeout_seconds)
        return OpenAIEmbeddingsClient(
            runtime_config=runtime_config,
            http_client=http_client,
            base_url=base_url,
            default_model=default_model,
        )

    def test_successful_single_text_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/v1/embeddings")
            self.assertEqual(request.headers["Authorization"], "Bearer demo")
            self.assertEqual(request.headers["User-Agent"], "Autonomous Company Research & Report Generation Agent")
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(set(body), {"model", "input"})
            self.assertEqual(body["model"], OPENAI_DEFAULT_EMBEDDING_MODEL)
            self.assertEqual(body["input"], ["Hello embeddings"])
            self.assertNotIn("api_key", body)
            self.assertNotIn("apikey", request.url.params)
            return httpx.Response(
                200,
                json={
                    "model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "data": [
                        {
                            "index": 0,
                            "embedding": [0.1, 0.2, 0.3],
                        }
                    ],
                    "usage": {"prompt_tokens": 4, "total_tokens": 4},
                },
            )

        client = self._build_client(handler)
        response = client.create_embeddings("Hello embeddings")

        self.assertEqual(response.model, OPENAI_DEFAULT_EMBEDDING_MODEL)
        self.assertEqual(response.data[0].index, 0)
        self.assertEqual(response.data[0].embedding, (0.1, 0.2, 0.3))

    def test_successful_multiple_text_request_maps_to_dto_and_dimensions(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["input"], ["One", "Two"])
            self.assertEqual(body["dimensions"], 3)
            return httpx.Response(
                200,
                json={
                    "model": "text-embedding-3-small",
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                        {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    ],
                    "usage": {"prompt_tokens": 6, "total_tokens": 6},
                },
            )

        client = self._build_client(handler)
        response = client.create_embeddings(("One", "Two"), dimensions=3)

        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[1].embedding, (0.4, 0.5, 0.6))

    def test_missing_api_key_raises_configuration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"model": OPENAI_DEFAULT_EMBEDDING_MODEL, "data": [], "usage": {"prompt_tokens": 0, "total_tokens": 0}})

        client = self._build_client(handler, api_key=None)

        with self.assertRaises(OpenAIEmbeddingsConfigurationError):
            client.create_embeddings("Hello embeddings")

    def test_http_401_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsAuthenticationError):
            client.create_embeddings("Hello embeddings")

    def test_http_403_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsAuthenticationError):
            client.create_embeddings("Hello embeddings")

    def test_http_429_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsRateLimitError):
            client.create_embeddings("Hello embeddings")

    def test_http_5xx_raises_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsTransportError):
            client.create_embeddings("Hello embeddings")

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsTimeoutError):
            client.create_embeddings("Hello embeddings")

    def test_malformed_json_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="{not-json")

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsResponseValidationError):
            client.create_embeddings("Hello embeddings")

    def test_malformed_embedding_item_raises_payload_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "data": [{"index": 0, "embedding": [True]}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsPayloadError):
            client.create_embeddings("Sensitive input text")

    def test_api_key_is_not_present_in_url_or_metadata(self) -> None:
        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                },
            )

        client = self._build_client(handler)
        client.create_embeddings("Hello embeddings")

        request = captured_requests[0]
        body = json.loads(request.content.decode("utf-8"))
        self.assertNotIn("apikey", request.url.params)
        self.assertNotIn("api_key", body)
        self.assertNotIn("apikey", body)
        self.assertEqual(request.headers["Authorization"], "Bearer demo")

    def test_full_input_text_does_not_appear_in_errors(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "data": [{"index": 0, "embedding": [True]}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )

        client = self._build_client(handler)

        with self.assertRaises(OpenAIEmbeddingsPayloadError) as context:
            client.create_embeddings("secret input that must not leak")

        self.assertNotIn("secret input that must not leak", str(context.exception))

