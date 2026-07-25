"""Tavily normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, date

from app.clients.tavily_dtos import TavilySearchResponse, TavilySearchResultDTO
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.providers import MarketFinding
from app.models.sources import SourceRecord
from app.utils.hashing import sha256_text

TAVILY_PROVIDER_NAME = "Tavily"


class TavilyNormalizationError(Exception):
    """Raised when Tavily data cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class TavilyNormalizationResult:
    """Canonical Tavily normalization output."""

    market_findings: tuple[MarketFinding, ...]
    sources: tuple[SourceRecord, ...]


def normalize_tavily_search_results(
    resolved_company: ResolvedCompany,
    response: TavilySearchResponse,
    runtime_config: RuntimeConfig | None = None,
) -> TavilyNormalizationResult:
    """Convert Tavily search results into canonical market records."""

    del runtime_config

    ordered_results = sorted(response.results, key=_result_sort_key)
    findings_by_id: dict[str, MarketFinding] = {}
    sources_by_id: dict[str, SourceRecord] = {}

    for result in ordered_results:
        finding, source = _normalize_result(resolved_company, result, response)
        if finding.finding_id not in findings_by_id:
            findings_by_id[finding.finding_id] = finding
        if source.source_id not in sources_by_id:
            sources_by_id[source.source_id] = source

    return TavilyNormalizationResult(
        market_findings=tuple(findings_by_id.values()),
        sources=tuple(sources_by_id.values()),
    )


def _normalize_result(
    resolved_company: ResolvedCompany,
    result: TavilySearchResultDTO,
    response: TavilySearchResponse,
) -> tuple[MarketFinding, SourceRecord]:
    if not isinstance(result, TavilySearchResultDTO):
        raise TavilyNormalizationError("Tavily normalization requires validated result DTOs.")

    normalized_url = result.url.strip()
    if not normalized_url:
        raise TavilyNormalizationError("Tavily result URL must not be empty.")

    published_at = result.published_date
    source_reference = result.title.strip()
    finding_id = _build_identifier("tavily_finding", resolved_company.company_name, normalized_url)
    source_id = _build_identifier("tavily_source", resolved_company.company_name, normalized_url)
    acquired_at = published_at or response.request_id or response.query or normalized_url

    finding = MarketFinding(
        finding_id=finding_id,
        company_name=resolved_company.company_name,
        title=result.title.strip(),
        source_id=source_id,
        summary=result.content,
        source_url=normalized_url,
        published_at=published_at,
    )
    source = SourceRecord(
        source_id=source_id,
        company_name=resolved_company.company_name,
        provider_name=TAVILY_PROVIDER_NAME,
        authority_level="secondary",
        acquired_at=acquired_at,
        source_url=normalized_url,
        raw_reference=source_reference,
        payload_type="search_result",
    )
    return finding, source


def _result_sort_key(result: TavilySearchResultDTO) -> tuple[int, float, str, str]:
    score = result.score if result.score is not None else 0.0
    return (
        1 if result.score is None else 0,
        -score,
        result.title.casefold(),
        result.url,
    )


def _build_identifier(prefix: str, company_name: str, normalized_url: str) -> str:
    digest = sha256_text("|".join([prefix, company_name, normalized_url]))[:16]
    return f"{prefix}_{digest}"
