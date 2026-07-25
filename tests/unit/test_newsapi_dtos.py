"""Unit tests for NewsAPI DTO validation and serialization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.newsapi_dtos import NewsApiArticleDTO, NewsApiEverythingResponse, NewsApiSourceDTO


class NewsApiDtoTests(unittest.TestCase):
    """Validation and serialization checks for NewsAPI DTOs."""

    def test_valid_source_article_and_response_are_serializable(self) -> None:
        source = NewsApiSourceDTO(id="reuters", name="Reuters")
        article = NewsApiArticleDTO(
            source=source,
            author="Jane Doe",
            title="Apple reports results",
            description="Apple reported quarterly results.",
            url="https://example.com/news/apple-results",
            url_to_image="https://example.com/image.jpg",
            published_at="2026-07-24T10:30:00Z",
            content="Article content",
        )
        response = NewsApiEverythingResponse(status="ok", total_results=1, articles=(article,))

        self.assertEqual(article.url, "https://example.com/news/apple-results")
        self.assertEqual(article.published_at, "2026-07-24T10:30:00Z")
        json.dumps(asdict(source))
        json.dumps(asdict(article))
        json.dumps(asdict(response))

    def test_blank_title_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiArticleDTO(
                source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                title=" ",
                url="https://example.com/news/apple-results",
                published_at="2026-07-24T10:30:00Z",
            )

    def test_invalid_url_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiArticleDTO(
                source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                title="Apple reports results",
                url="not-a-url",
                published_at="2026-07-24T10:30:00Z",
            )

    def test_invalid_publication_timestamp_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiArticleDTO(
                source=NewsApiSourceDTO(id="reuters", name="Reuters"),
                title="Apple reports results",
                url="https://example.com/news/apple-results",
                published_at="invalid-timestamp",
            )

    def test_malformed_article_object_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiArticleDTO(  # type: ignore[arg-type]
                source={"name": "Reuters"},
                title="Apple reports results",
                url="https://example.com/news/apple-results",
                published_at="2026-07-24T10:30:00Z",
            )

    def test_malformed_response_payload_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiEverythingResponse(status="ok", total_results=-1, articles=())

    def test_response_rejects_non_dto_articles(self) -> None:
        with self.assertRaises(ValueError):
            NewsApiEverythingResponse(
                status="ok",
                total_results=1,
                articles=(  # type: ignore[arg-type]
                    {"source": {"name": "Reuters"}, "title": "Apple reports results", "url": "https://example.com", "published_at": "2026-07-24T10:30:00Z"},
                ),
            )
