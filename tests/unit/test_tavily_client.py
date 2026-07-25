"""Unit tests for the Tavily client."""

from __future__ import annotations

import json
import unittest

import httpx

from app.clients.tavily_client import (
    TavilyAuthenticationError,
    TavilyClient,
    TavilyConfigurationError,
    TavilyPayloadError,
    TavilyRateLimitError,
    TavilyResponseValidationError,
    TavilyTimeoutError,
    TavilyTransportError,
)
from app.models.execution import RuntimeConfig


class TavilyClientTests(unittest.TestCase):
    """Offline tests for Tavily transport and validation."""

    def _build_client(
        self,
        handler,
        *,
        api_key: str | None = "demo",
        max_retries: int = 0,
        timeout_seconds: float = 1.0,
    ) -> TavilyClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(tavily_api_key=api_key, max_retries=max_retries, timeout_seconds=timeout_seconds)
        return TavilyClient(runtime_config=runtime_config, http_client=http_client)

    def test_successful_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/search")
            self.assertEqual(request.headers["Authorization"], "Bearer demo")
            self.assertEqual(request.headers["User-Agent"], "Autonomous Company Research & Report Generation Agent")
            self.assertNotIn("apikey", request.url.params)
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(
                set(body),
                {"query", "topic", "max_results", "include_answer", "include_raw_content", "days"},
            )
            self.assertEqual(body["query"], '"Apple Inc." company market industry competitors strategy AAPL')
            self.assertEqual(body["topic"], "general")
            self.assertEqual(body["max_results"], 5)
            self.assertFalse(body["include_answer"])
            self.assertFalse(body["include_raw_content"])
            return httpx.Response(
                200,
                json={
                    "query": "Apple",
                    "answer": None,
                    "response_time": 0.42,
                    "request_id": "req_1",
                    "results": [
                        {
                            "title": "Apple market overview",
                            "url": "https://example.com/research/apple-overview",
                            "content": "Apple operates in consumer technology.",
                            "score": 0.91,
                            "published_date": "2026-07-24T10:30:00Z",
                        }
                    ],
                },
            )

        client = self._build_client(handler)
        response = client.search('"Apple Inc." company market industry competitors strategy AAPL')

        self.assertEqual(response.query, "Apple")
        self.assertEqual(response.results[0].title, "Apple market overview")

    def test_missing_api_key_raises_configuration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"query": "Apple", "results": []})

        client = self._build_client(handler, api_key=None)

        with self.assertRaises(TavilyConfigurationError):
            client.search("Apple")

    def test_http_401_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        client = self._build_client(handler)

        with self.assertRaises(TavilyAuthenticationError):
            client.search("Apple")

    def test_http_403_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        client = self._build_client(handler)

        with self.assertRaises(TavilyAuthenticationError):
            client.search("Apple")

    def test_http_429_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = self._build_client(handler)

        with self.assertRaises(TavilyRateLimitError):
            client.search("Apple")

    def test_http_5xx_raises_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = self._build_client(handler)

        with self.assertRaises(TavilyTransportError):
            client.search("Apple")

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(TavilyTimeoutError):
            client.search("Apple")

    def test_malformed_json_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="{not-json")

        client = self._build_client(handler)

        with self.assertRaises(TavilyResponseValidationError):
            client.search("Apple")

    def test_malformed_successful_payload_raises_payload_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"query": "Apple", "results": [{"title": "Apple"}]})

        client = self._build_client(handler)

        with self.assertRaises(TavilyResponseValidationError):
            client.search("Apple")

    def test_non_finite_response_time_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text='{"query":"Apple","response_time": NaN,"results":[]}')

        client = self._build_client(handler)

        with self.assertRaises(TavilyResponseValidationError):
            client.search("Apple")

    def test_api_key_is_not_present_in_query_or_body(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"query": "Apple", "results": []})

        client = self._build_client(handler)
        client.search("Apple")

        request = captured[0]
        self.assertNotIn("apikey", request.url.params)
        body = json.loads(request.content.decode("utf-8"))
        self.assertNotIn("api_key", body)
        self.assertNotIn("apikey", body)
