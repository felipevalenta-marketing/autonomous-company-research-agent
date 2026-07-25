"""NewsAPI normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC

from app.clients.newsapi_dtos import NewsApiArticleDTO, NewsApiEverythingResponse
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.providers import NewsEvent
from app.models.sources import SourceRecord
from app.utils.hashing import sha256_text

NEWS_API_PROVIDER_NAME = "NewsAPI"


class NewsApiNormalizationError(Exception):
    """Raised when NewsAPI data cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class NewsNormalizationResult:
    """Canonical NewsAPI normalization output."""

    news_events: tuple[NewsEvent, ...]
    sources: tuple[SourceRecord, ...]


def normalize_newsapi_data(
    resolved_company: ResolvedCompany,
    response: NewsApiEverythingResponse,
    runtime_config: RuntimeConfig | None = None,
) -> NewsNormalizationResult:
    """Convert NewsAPI articles into canonical news records."""

    del runtime_config

    ordered_articles = sorted(response.articles, key=_article_sort_key)
    events_by_id: dict[str, NewsEvent] = {}
    sources_by_id: dict[str, SourceRecord] = {}

    for article in ordered_articles:
        news_event, source_record = _normalize_article(resolved_company, article)
        events_by_id[news_event.event_id] = news_event
        sources_by_id[source_record.source_id] = source_record

    return NewsNormalizationResult(
        news_events=tuple(events_by_id.values()),
        sources=tuple(sources_by_id.values()),
    )


def _normalize_article(
    resolved_company: ResolvedCompany,
    article: NewsApiArticleDTO,
) -> tuple[NewsEvent, SourceRecord]:
    if not isinstance(article, NewsApiArticleDTO):
        raise NewsApiNormalizationError("NewsAPI normalization requires validated article DTOs.")

    source_name = article.source.name.strip()
    normalized_url = article.url.strip()
    if not normalized_url:
        raise NewsApiNormalizationError("NewsAPI article URL must not be empty.")

    summary = article.description or article.content
    event_id = _build_identifier("news_event", resolved_company.company_name, normalized_url)
    source_id = _build_identifier("news_source", resolved_company.company_name, normalized_url)
    published_at = article.published_at.strip()

    news_event = NewsEvent(
        event_id=event_id,
        company_name=resolved_company.company_name,
        title=article.title.strip(),
        published_at=published_at,
        source_id=source_id,
        summary=summary,
        url=normalized_url,
    )
    source_record = SourceRecord(
        source_id=source_id,
        company_name=resolved_company.company_name,
        provider_name=NEWS_API_PROVIDER_NAME,
        authority_level="secondary",
        acquired_at=published_at,
        source_url=normalized_url,
        raw_reference=source_name,
        payload_type="news_article",
    )
    return news_event, source_record


def _article_sort_key(article: NewsApiArticleDTO) -> tuple[str, str, str]:
    published_at = datetime.fromisoformat(article.published_at.replace("Z", "+00:00")).astimezone(UTC)
    return (
        -published_at.timestamp(),
        article.title.casefold(),
        article.url,
    )


def _build_identifier(prefix: str, company_name: str, normalized_url: str) -> str:
    digest = sha256_text("|".join([prefix, company_name, normalized_url]))[:16]
    return f"{prefix}_{digest}"
