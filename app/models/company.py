"""Company identity models."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class ResolvedCompany:
    """Resolved public company identity."""

    company_name: str
    ticker: str | None = None
    cik: str | None = None
    exchange: str | None = None
    country: str | None = None
    security_type: str | None = None
    company_id: str | None = None
    website_url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.company_name, "company_name")

