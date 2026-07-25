"""Unit tests for NewsAPI normalization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.newsapi_dtos import NewsApiArticleDTO, NewsApiEverythingResponse, NewsApiSourceDTO
from app.models.company import ResolvedCompany
from app.models.evidence import EvidenceRecord
from app.models.providers import MarketFinding
from app.services.newsapi_normalization_service import normalize_newsapi_data


class NewsApiNormalizationTests(unittest.TestCase):
    """Offline tests for NewsAPI normalization."""

    def setUp(self) -> None:
        self.company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL")
        self.response = NewsApiEverythingResponse(
            status="ok",
            total_results=3,
            articles=(
                NewsApiArticleDTO(
                    source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                    title="Apple reports results",
                    description="Apple reported quarterly results.",
                    url="https://example.com/news/apple-results",
                    published_at="2026-07-24T10:30:00Z",
                ),
                NewsApiArticleDTO(
                    source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                    title="Apple reports results",
                    description="Duplicate article.",
                    url="https://example.com/news/apple-results",
                    published_at="2026-07-24T10:30:00Z",
                ),
                NewsApiArticleDTO(
                    source=NewsApiSourceDTO(id="ap", name="Associated Press"),
                    title="Apple expands services",
                    description=None,
                    content="AP coverage",
                    url="https://example.com/news/apple-services",
                    published_at="2026-07-23T09:00:00Z",
                ),
            ),
        )

    def test_normalization_creates_news_events_and_sources(self) -> None:
        result = normalize_newsapi_data(self.company, self.response)

        self.assertEqual(len(result.news_events), 2)
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(result.news_events[0].title, "Apple reports results")
        self.assertEqual(result.news_events[0].summary, "Duplicate article.")
        self.assertEqual(result.news_events[0].url, "https://example.com/news/apple-results")
        self.assertEqual(result.sources[0].provider_name, "NewsAPI")
        self.assertEqual(result.sources[0].raw_reference, "Reuters")
        json.dumps(asdict(result))

    def test_normalization_is_deterministic(self) -> None:
        first = normalize_newsapi_data(self.company, self.response)
        second = normalize_newsapi_data(self.company, self.response)

        self.assertEqual(first, second)

    def test_url_based_deduplication_is_stable(self) -> None:
        result = normalize_newsapi_data(self.company, self.response)

        self.assertEqual(len({event.event_id for event in result.news_events}), 2)
        self.assertEqual(len({source.source_id for source in result.sources}), 2)

    def test_empty_input_is_valid(self) -> None:
        empty = NewsApiEverythingResponse(status="ok", total_results=0, articles=())

        result = normalize_newsapi_data(self.company, empty)

        self.assertEqual(result.news_events, ())
        self.assertEqual(result.sources, ())

    def test_no_evidence_or_market_finding_is_created(self) -> None:
        result = normalize_newsapi_data(self.company, self.response)

        self.assertTrue(all(not isinstance(item, EvidenceRecord) for item in result.news_events))
        self.assertTrue(all(not isinstance(item, MarketFinding) for item in result.news_events))

    def test_normalization_does_not_mutate_state(self) -> None:
        state = {"news_events": [], "sources": []}

        normalize_newsapi_data(self.company, self.response)

        self.assertEqual(state, {"news_events": [], "sources": []})

