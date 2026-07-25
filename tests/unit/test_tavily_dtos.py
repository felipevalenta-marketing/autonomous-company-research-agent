"""Unit tests for Tavily DTO validation and serialization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.tavily_dtos import TavilySearchResponse, TavilySearchResultDTO


class TavilyDtoTests(unittest.TestCase):
    """Validation and serialization checks for Tavily DTOs."""

    def test_valid_search_result_and_response_are_serializable(self) -> None:
        result = TavilySearchResultDTO(
            title="Apple Inc. market overview",
            url="https://example.com/research/apple-overview",
            content="Apple operates in consumer technology.",
            score=0.91,
            published_date="2026-07-24T10:30:00Z",
        )
        response = TavilySearchResponse(
            query='"Apple Inc." company market industry competitors strategy AAPL',
            answer=None,
            results=(result,),
            response_time=0.42,
            request_id="req_1",
        )

        self.assertEqual(result.url, "https://example.com/research/apple-overview")
        self.assertEqual(result.published_date, "2026-07-24T10:30:00Z")
        json.dumps(asdict(result))
        json.dumps(asdict(response))

    def test_blank_title_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(
                title=" ",
                url="https://example.com/research/apple-overview",
            )

    def test_blank_url_rejection(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url=" ")

    def test_invalid_url_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url="not-a-url")

    def test_invalid_score_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url="https://example.com", score=-1.0)

    def test_non_finite_score_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url="https://example.com", score=float("nan"))

        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url="https://example.com", score=float("inf"))

    def test_invalid_publication_date_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(title="Apple", url="https://example.com", published_date="not-a-date")

    def test_malformed_result_object_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResultDTO(  # type: ignore[arg-type]
                title="Apple",
                url="https://example.com",
                score={"bad": "value"},
            )

    def test_malformed_top_level_response_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResponse(query="Apple", results=(object(),))  # type: ignore[arg-type]

    def test_non_dto_results_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResponse(query="Apple", results=({"title": "Apple"},))  # type: ignore[arg-type]

    def test_non_finite_response_time_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TavilySearchResponse(query="Apple", results=(), response_time=float("nan"))

        with self.assertRaises(ValueError):
            TavilySearchResponse(query="Apple", results=(), response_time=float("inf"))
