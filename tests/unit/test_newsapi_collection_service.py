"""Unit tests for NewsAPI collection orchestration."""

from __future__ import annotations

import inspect
import sys
import unittest

from app.clients.newsapi_client import NewsApiAuthenticationError, NewsApiPayloadError
from app.clients.newsapi_dtos import NewsApiArticleDTO, NewsApiEverythingResponse, NewsApiSourceDTO
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.services.newsapi_collection_service import (
    NewsApiCollectionInputError,
    collect_recent_news,
)


class FakeNewsApiClient:
    """In-memory NewsAPI client for offline orchestration tests."""

    def __init__(self, response: NewsApiEverythingResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search_everything(
        self,
        query: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str = "en",
        sort_by: str = "publishedAt",
        page_size: int = 20,
        page: int = 1,
    ) -> NewsApiEverythingResponse:
        self.calls.append(
            {
                "query": query,
                "from_date": from_date,
                "to_date": to_date,
                "language": language,
                "sort_by": sort_by,
                "page_size": page_size,
                "page": page,
            }
        )
        return self.response


class NewsApiCollectionServiceTests(unittest.TestCase):
    """Offline tests for NewsAPI collection orchestration."""

    def setUp(self) -> None:
        self.company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL")
        self.runtime_config = RuntimeConfig(news_api_key="demo")
        self.response = NewsApiEverythingResponse(
            status="ok",
            total_results=1,
            articles=(
                NewsApiArticleDTO(
                    source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                    title="Apple reports results",
                    description="Apple reported quarterly results.",
                    url="https://example.com/news/apple-results",
                    published_at="2026-07-24T10:30:00Z",
                ),
            ),
        )

    def test_collect_recent_news_builds_deterministic_query(self) -> None:
        client = FakeNewsApiClient(self.response)

        result = collect_recent_news(
            self.company,
            client,
            self.runtime_config,
            from_date="2026-07-20",
            to_date="2026-07-24",
            language="en",
            page_size=25,
            page=1,
        )

        self.assertEqual(result, self.response)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["query"], '("Apple Inc." OR AAPL)')
        self.assertEqual(call["from_date"], "2026-07-20")
        self.assertEqual(call["to_date"], "2026-07-24")
        self.assertEqual(call["language"], "en")
        self.assertEqual(call["page_size"], 25)
        self.assertEqual(call["page"], 1)

    def test_collect_recent_news_uses_company_name_only_when_ticker_missing(self) -> None:
        client = FakeNewsApiClient(self.response)
        company = ResolvedCompany(company_name="Apple Inc.")

        collect_recent_news(company, client, self.runtime_config)

        self.assertEqual(client.calls[0]["query"], '"Apple Inc."')

    def test_collect_recent_news_escapes_embedded_quotes_in_company_name(self) -> None:
        client = FakeNewsApiClient(self.response)
        company = ResolvedCompany(company_name='The "Quoted" Company, Inc.', ticker="QCO")

        collect_recent_news(company, client, self.runtime_config)

        self.assertEqual(client.calls[0]["query"], '("The Quoted Company, Inc." OR QCO)')

    def test_collect_recent_news_rejects_missing_company_name(self) -> None:
        client = FakeNewsApiClient(self.response)
        company = ResolvedCompany(company_name="Apple Inc.")

        object.__setattr__(company, "company_name", " ")

        with self.assertRaises(NewsApiCollectionInputError):
            collect_recent_news(company, client, self.runtime_config)

    def test_collect_recent_news_is_deterministic(self) -> None:
        client = FakeNewsApiClient(self.response)

        first = collect_recent_news(self.company, client, self.runtime_config)
        second = collect_recent_news(self.company, client, self.runtime_config)

        self.assertEqual(first, second)
        self.assertEqual(len(client.calls), 2)

    def test_collect_recent_news_does_not_mutate_state_or_import_langgraph(self) -> None:
        state = {"news_events": [], "sources": []}
        client = FakeNewsApiClient(self.response)

        collect_recent_news(self.company, client, self.runtime_config)

        self.assertEqual(state, {"news_events": [], "sources": []})
        self.assertNotIn("langgraph", sys.modules)
        self.assertNotIn("state", inspect.signature(collect_recent_news).parameters)

    def test_client_errors_propagate(self) -> None:
        class ErrorClient(FakeNewsApiClient):
            def search_everything(self, *args, **kwargs):  # type: ignore[override]
                raise NewsApiAuthenticationError("NewsAPI rejected the configured credentials.")

        client = ErrorClient(self.response)

        with self.assertRaises(NewsApiAuthenticationError):
            collect_recent_news(self.company, client, self.runtime_config)

    def test_invalid_page_size_raises_input_error(self) -> None:
        client = FakeNewsApiClient(self.response)

        with self.assertRaises(NewsApiCollectionInputError):
            collect_recent_news(self.company, client, self.runtime_config, page_size=0)

    def test_page_size_is_bounded(self) -> None:
        client = FakeNewsApiClient(self.response)

        collect_recent_news(self.company, client, self.runtime_config, page_size=250)

        self.assertEqual(client.calls[0]["page_size"], 100)
