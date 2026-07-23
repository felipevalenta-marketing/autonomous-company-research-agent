"""Provider-domain record models."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class FinancialMetric:
    """Normalized financial metric."""

    metric_id: str
    company_name: str
    metric_name: str
    value: float
    period: str
    source_id: str
    currency: str | None = None
    unit: str | None = None
    is_calculated: bool = False

    def __post_init__(self) -> None:
        _require_text(self.metric_id, "metric_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.metric_name, "metric_name")
        _require_text(self.period, "period")
        _require_text(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """Normalized news record."""

    event_id: str
    company_name: str
    title: str
    published_at: str
    source_id: str
    summary: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.title, "title")
        _require_text(self.published_at, "published_at")
        _require_text(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class MarketFinding:
    """Normalized market research record."""

    finding_id: str
    company_name: str
    title: str
    source_id: str
    summary: str | None = None
    source_url: str | None = None
    published_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.finding_id, "finding_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.title, "title")
        _require_text(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class RAGResult:
    """Retrieval result used before conversion to evidence."""

    result_id: str
    company_name: str
    document_id: str
    chunk_id: str
    source_id: str
    text: str
    similarity_score: float | None = None
    retrieval_scope: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.result_id, "result_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.document_id, "document_id")
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.source_id, "source_id")
        _require_text(self.text, "text")

