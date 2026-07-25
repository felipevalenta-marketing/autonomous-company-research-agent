"""Unit tests for Tavily collection orchestration."""

from __future__ import annotations

import inspect
import sys
import unittest

from app.clients.tavily_dtos import TavilySearchResponse, TavilySearchResultDTO
from app.models.company import ResolvedCompany
from app.services.tavily_collection_service import (
    TavilyCollectionInputError,
    collect_market_research,
)


class FakeTavilyClient:
    """In-memory Tavily client for offline orchestration tests."""

    def __init__(self, response: TavilySearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        query: str,
        *,
        topic: str = "general",
        max_results: int = 5,
        include_answer: bool = False,
        include_raw_content: bool = False,
        days: int | None = 30,
    ) -> TavilySearchResponse:
        self.calls.append(
            {
                "query": query,
                "topic": topic,
                "max_results": max_results,
                "include_answer": include_answer,
                "include_raw_content": include_raw_content,
                "days": days,
            }
        )
        return self.response


class TavilyCollectionServiceTests(unittest.TestCase):
    """Offline tests for Tavily collection orchestration."""

    def setUp(self) -> None:
        self.company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL")
        self.response = TavilySearchResponse(
            query='"Apple Inc." company market industry competitors strategy AAPL',
            results=(
                TavilySearchResultDTO(
                    title="Apple market overview",
                    url="https://example.com/research/apple-overview",
                    content="Apple operates in consumer technology.",
                    score=0.91,
                    published_date="2026-07-24T10:30:00Z",
                ),
            ),
        )

    def test_collect_market_research_builds_deterministic_query(self) -> None:
        client = FakeTavilyClient(self.response)

        result = collect_market_research(
            self.company,
            client,
            topic="general",
            max_results=8,
            include_answer=False,
            include_raw_content=False,
            days=30,
        )

        self.assertEqual(result, self.response)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["query"], '"Apple Inc." company market industry competitors strategy AAPL')
        self.assertEqual(call["topic"], "general")
        self.assertEqual(call["max_results"], 8)
        self.assertFalse(call["include_answer"])
        self.assertFalse(call["include_raw_content"])
        self.assertEqual(call["days"], 30)

    def test_collect_market_research_uses_company_name_only_when_ticker_missing(self) -> None:
        client = FakeTavilyClient(self.response)
        company = ResolvedCompany(company_name="Apple Inc.")

        collect_market_research(company, client)

        self.assertEqual(client.calls[0]["query"], '"Apple Inc." company market industry competitors strategy')

    def test_collect_market_research_preserves_company_punctuation(self) -> None:
        client = FakeTavilyClient(self.response)
        company = ResolvedCompany(company_name="Berkshire Hathaway, Inc.", ticker="brka")

        collect_market_research(company, client)

        self.assertEqual(client.calls[0]["query"], '"Berkshire Hathaway, Inc." company market industry competitors strategy BRKA')

    def test_collect_market_research_rejects_missing_company_name(self) -> None:
        client = FakeTavilyClient(self.response)
        company = ResolvedCompany(company_name="Apple Inc.")

        object.__setattr__(company, "company_name", " ")

        with self.assertRaises(TavilyCollectionInputError):
            collect_market_research(company, client)

    def test_collect_market_research_is_deterministic(self) -> None:
        client = FakeTavilyClient(self.response)

        first = collect_market_research(self.company, client)
        second = collect_market_research(self.company, client)

        self.assertEqual(first, second)
        self.assertEqual(len(client.calls), 2)

    def test_collect_market_research_does_not_mutate_state_or_import_langgraph(self) -> None:
        state = {"market_findings": [], "sources": []}
        client = FakeTavilyClient(self.response)

        collect_market_research(self.company, client)

        self.assertEqual(state, {"market_findings": [], "sources": []})
        self.assertNotIn("langgraph", sys.modules)
        self.assertNotIn("state", inspect.signature(collect_market_research).parameters)

    def test_invalid_max_results_raises_input_error(self) -> None:
        client = FakeTavilyClient(self.response)

        with self.assertRaises(TavilyCollectionInputError):
            collect_market_research(self.company, client, max_results=0)

    def test_max_results_is_bounded(self) -> None:
        client = FakeTavilyClient(self.response)

        collect_market_research(self.company, client, max_results=999)

        self.assertEqual(client.calls[0]["max_results"], 10)
