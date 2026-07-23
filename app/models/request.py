"""Research request model."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str | None, field_name: str) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    """User intent for a single-company research run."""

    company_name: str | None = None
    ticker: str | None = None
    research_goal: str = "Executive company research"
    report_language: str = "en"
    report_currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.company_name and not self.ticker:
            raise ValueError("company_name or ticker must be provided.")
        if self.company_name is not None:
            _require_text(self.company_name, "company_name")
        if self.ticker is not None:
            _require_text(self.ticker, "ticker")
        _require_text(self.research_goal, "research_goal")
        _require_text(self.report_language, "report_language")
        _require_text(self.report_currency, "report_currency")

