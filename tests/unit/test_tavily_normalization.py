"""Unit tests for Tavily normalization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.tavily_dtos import TavilySearchResponse, TavilySearchResultDTO
from app.models.company import ResolvedCompany
from app.models.evidence import EvidenceRecord
from app.models.providers import NewsEvent
from app.services.tavily_normalization_service import normalize_tavily_search_results


class TavilyNormalizationTests(unittest.TestCase):
    """Offline tests for Tavily normalization."""

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
                TavilySearchResultDTO(
                    title="Apple market overview",
                    url="https://example.com/research/apple-overview",
                    content="Duplicate content.",
                    score=0.75,
                    published_date="2026-07-24T10:30:00Z",
                ),
                TavilySearchResultDTO(
                    title="Apple strategy review",
                    url="https://example.com/research/apple-strategy",
                    content="Strategy commentary.",
                    score=0.80,
                ),
            ),
        )

    def test_normalization_creates_market_findings_and_sources(self) -> None:
        result = normalize_tavily_search_results(self.company, self.response)

        self.assertEqual(len(result.market_findings), 2)
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(result.market_findings[0].title, "Apple market overview")
        self.assertEqual(result.market_findings[0].summary, "Apple operates in consumer technology.")
        self.assertEqual(result.market_findings[0].source_url, "https://example.com/research/apple-overview")
        self.assertEqual(result.sources[0].provider_name, "Tavily")
        self.assertEqual(result.sources[0].raw_reference, "Apple market overview")
        json.dumps(asdict(result))

    def test_normalization_is_deterministic(self) -> None:
        first = normalize_tavily_search_results(self.company, self.response)
        second = normalize_tavily_search_results(self.company, self.response)

        self.assertEqual(first, second)

    def test_url_based_deduplication_is_stable(self) -> None:
        result = normalize_tavily_search_results(self.company, self.response)

        self.assertEqual(len({finding.finding_id for finding in result.market_findings}), 2)
        self.assertEqual(len({source.source_id for source in result.sources}), 2)

    def test_empty_input_is_valid(self) -> None:
        empty = TavilySearchResponse(query="Apple", results=())

        result = normalize_tavily_search_results(self.company, empty)

        self.assertEqual(result.market_findings, ())
        self.assertEqual(result.sources, ())

    def test_no_evidence_or_news_event_is_created(self) -> None:
        result = normalize_tavily_search_results(self.company, self.response)

        self.assertTrue(all(not isinstance(item, EvidenceRecord) for item in result.market_findings))
        self.assertTrue(all(not isinstance(item, NewsEvent) for item in result.market_findings))

    def test_normalization_does_not_mutate_state(self) -> None:
        state = {"market_findings": [], "sources": []}

        normalize_tavily_search_results(self.company, self.response)

        self.assertEqual(state, {"market_findings": [], "sources": []})

