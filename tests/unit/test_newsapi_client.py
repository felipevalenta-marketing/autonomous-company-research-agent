"""Unit tests for the NewsAPI client."""

from __future__ import annotations

import unittest

import httpx

from app.clients.newsapi_client import (
    NewsApiAuthenticationError,
    NewsApiClient,
    NewsApiConfigurationError,
    NewsApiPayloadError,
    NewsApiRateLimitError,
    NewsApiResponseValidationError,
    NewsApiTimeoutError,
    NewsApiTransportError,
)
from app.models.execution import RuntimeConfig


class NewsApiClientTests(unittest.TestCase):
    """Offline tests for NewsAPI transport and validation."""

    def _build_client(
        self,
        handler,
        *,
        api_key: str | None = "demo",
        max_retries: int = 0,
        timeout_seconds: float = 1.0,
    ) -> NewsApiClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(news_api_key=api_key, max_retries=max_retries, timeout_seconds=timeout_seconds)
        return NewsApiClient(runtime_config=runtime_config, http_client=http_client)

    def test_successful_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v2/everything")
            self.assertEqual(request.url.params["q"], '"Apple Inc." OR AAPL')
            self.assertEqual(request.url.params["language"], "en")
            self.assertEqual(request.url.params["sortBy"], "publishedAt")
            self.assertEqual(request.url.params["pageSize"], "20")
            self.assertEqual(request.headers["X-Api-Key"], "demo")
            self.assertNotIn("apikey", request.url.params)
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "totalResults": 1,
                    "articles": [
                        {
                            "source": {"id": "reuters", "name": "Reuters"},
                            "author": "Jane Doe",
                            "title": "Apple reports results",
                            "description": "Apple reported quarterly results.",
                            "url": "https://example.com/news/apple-results",
                            "urlToImage": "https://example.com/image.jpg",
                            "publishedAt": "2026-07-24T10:30:00Z",
                            "content": "Article content",
                        }
                    ],
                },
            )

        client = self._build_client(handler)
        response = client.search_everything('"Apple Inc." OR AAPL')

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.total_results, 1)
        self.assertEqual(response.articles[0].source.name, "Reuters")

    def test_status_error_response_raises_payload_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "error", "code": "apiKeyInvalid", "message": "Invalid API key"})

        client = self._build_client(handler)

        with self.assertRaises(NewsApiAuthenticationError):
            client.search_everything("Apple")

    def test_http_400_raises_payload_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        client = self._build_client(handler)

        with self.assertRaises(NewsApiPayloadError):
            client.search_everything("Apple")

    def test_http_401_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        client = self._build_client(handler)

        with self.assertRaises(NewsApiAuthenticationError):
            client.search_everything("Apple")

    def test_http_429_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = self._build_client(handler)

        with self.assertRaises(NewsApiRateLimitError):
            client.search_everything("Apple")

    def test_http_5xx_raises_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = self._build_client(handler)

        with self.assertRaises(NewsApiTransportError):
            client.search_everything("Apple")

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(NewsApiTimeoutError):
            client.search_everything("Apple")

    def test_malformed_json_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="{not-json")

        client = self._build_client(handler)

        with self.assertRaises(NewsApiResponseValidationError):
            client.search_everything("Apple")

    def test_missing_articles_field_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok", "totalResults": 0})

        client = self._build_client(handler)

        with self.assertRaises(NewsApiResponseValidationError):
            client.search_everything("Apple")

    def test_missing_api_key_raises_configuration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok", "totalResults": 0, "articles": []})

        client = self._build_client(handler, api_key=None)

        with self.assertRaises(NewsApiConfigurationError):
            client.search_everything("Apple")

    def test_api_key_is_not_present_in_public_params(self) -> None:
        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"status": "ok", "totalResults": 0, "articles": []})

        client = self._build_client(handler)
        client.search_everything("Apple")

        request = captured_requests[0]
        self.assertNotIn("apikey", request.url.params)
        self.assertEqual(request.headers["X-Api-Key"], "demo")

