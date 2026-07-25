"""Application-service orchestration for Tavily collection."""

from __future__ import annotations

from typing import Protocol

from app.clients.tavily_dtos import TavilySearchResponse
from app.config.constants import (
    TAVILY_DEFAULT_LOOKBACK_DAYS,
    TAVILY_DEFAULT_MAX_RESULTS,
    TAVILY_DEFAULT_TOPIC,
)
from app.models.company import ResolvedCompany


class TavilyCollectionError(Exception):
    """Base exception for Tavily collection failures."""


class TavilyCollectionInputError(TavilyCollectionError):
    """Raised when the Tavily collection service receives invalid input."""


class TavilyCollectionClient(Protocol):
    """Minimal Tavily client contract required by collection."""

    def search(
        self,
        query: str,
        *,
        topic: str = TAVILY_DEFAULT_TOPIC,
        max_results: int = TAVILY_DEFAULT_MAX_RESULTS,
        include_answer: bool = False,
        include_raw_content: bool = False,
        days: int | None = TAVILY_DEFAULT_LOOKBACK_DAYS,
    ) -> TavilySearchResponse:
        """Return a validated Tavily search response."""


def collect_market_research(
    resolved_company: ResolvedCompany,
    tavily_client: TavilyCollectionClient,
    *,
    topic: str = TAVILY_DEFAULT_TOPIC,
    max_results: int = TAVILY_DEFAULT_MAX_RESULTS,
    include_answer: bool = False,
    include_raw_content: bool = False,
    days: int | None = TAVILY_DEFAULT_LOOKBACK_DAYS,
) -> TavilySearchResponse:
    """Collect one deterministic Tavily search response for a resolved company."""

    company_name = _normalize_company_name(resolved_company.company_name)
    ticker = _normalize_ticker(resolved_company.ticker)
    query = _build_query(company_name, ticker)

    return tavily_client.search(
        query,
        topic=_normalize_topic(topic),
        max_results=_normalize_max_results(max_results),
        include_answer=bool(include_answer),
        include_raw_content=bool(include_raw_content),
        days=_normalize_days(days) if days is not None else None,
    )


def _build_query(company_name: str, ticker: str | None) -> str:
    base = f'"{company_name}" company market industry competitors strategy'
    if ticker is None:
        return base
    return f'{base} {ticker}'


def _normalize_company_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise TavilyCollectionInputError("Resolved company must include a company name.")
    return stripped.replace('"', "")


def _normalize_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.upper()


def _normalize_topic(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise TavilyCollectionInputError("topic must not be empty.")
    return stripped.lower()


def _normalize_max_results(value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise TavilyCollectionInputError("max_results must be positive.")
    return min(value, 10)


def _normalize_days(value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise TavilyCollectionInputError("days must be positive.")
    return min(value, 365)

