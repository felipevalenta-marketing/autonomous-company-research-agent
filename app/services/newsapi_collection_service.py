"""Application-service orchestration for NewsAPI collection."""

from __future__ import annotations

from typing import Protocol

from app.clients.newsapi_client import NewsApiEverythingResponse
from app.config.constants import (
    NEWS_API_DEFAULT_LANGUAGE,
    NEWS_API_DEFAULT_PAGE_SIZE,
    NEWS_API_DEFAULT_SORT_BY,
    NEWS_API_MAX_PAGE_SIZE,
)
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig


class NewsApiCollectionError(Exception):
    """Base exception for NewsAPI collection failures."""


class NewsApiCollectionInputError(NewsApiCollectionError):
    """Raised when the NewsAPI collection service receives invalid input."""


class NewsApiCollectionClient(Protocol):
    """Minimal NewsAPI client contract required by collection."""

    def search_everything(
        self,
        query: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str = NEWS_API_DEFAULT_LANGUAGE,
        sort_by: str = NEWS_API_DEFAULT_SORT_BY,
        page_size: int = NEWS_API_DEFAULT_PAGE_SIZE,
        page: int = 1,
    ) -> NewsApiEverythingResponse:
        """Return a validated NewsAPI everything response."""


def collect_recent_news(
    resolved_company: ResolvedCompany,
    news_client: NewsApiCollectionClient,
    runtime_config: RuntimeConfig | None = None,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    language: str = NEWS_API_DEFAULT_LANGUAGE,
    page_size: int = NEWS_API_DEFAULT_PAGE_SIZE,
    page: int = 1,
) -> NewsApiEverythingResponse:
    """Collect a deterministic NewsAPI response for a resolved company."""

    del runtime_config

    company_name = _normalize_company_name(resolved_company.company_name)
    ticker = _normalize_ticker(resolved_company.ticker)
    query = _build_query(company_name, ticker)

    return news_client.search_everything(
        query,
        from_date=_normalize_optional_text(from_date),
        to_date=_normalize_optional_text(to_date),
        language=_normalize_optional_text(language) or NEWS_API_DEFAULT_LANGUAGE,
        sort_by=NEWS_API_DEFAULT_SORT_BY,
        page_size=_normalize_page_size(page_size),
        page=_normalize_page(page),
    )


def _build_query(company_name: str, ticker: str | None) -> str:
    sanitized_company_name = company_name.replace('"', "").strip()
    if ticker is None:
        return f'"{sanitized_company_name}"'
    return f'("{sanitized_company_name}" OR {ticker})'


def _normalize_company_name(value: str) -> str:
    text = _normalize_optional_text(value)
    if text is None:
        raise NewsApiCollectionInputError("Resolved company must include a company name.")
    return " ".join(text.split())


def _normalize_ticker(value: str | None) -> str | None:
    text = _normalize_optional_text(value)
    if text is None:
        return None
    return text.upper()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_page_size(value: int) -> int:
    if value <= 0:
        raise NewsApiCollectionInputError("page_size must be positive.")
    return min(value, NEWS_API_MAX_PAGE_SIZE)


def _normalize_page(value: int) -> int:
    if value <= 0:
        raise NewsApiCollectionInputError("page must be positive.")
    return value
