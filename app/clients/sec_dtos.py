"""SEC provider-specific DTOs."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class SecTickerRecord:
    """Validated SEC ticker dataset record."""

    cik: int
    ticker: str
    title: str

    def __post_init__(self) -> None:
        if self.cik <= 0:
            raise ValueError("cik must be a positive integer.")
        _require_text(self.ticker, "ticker")
        _require_text(self.title, "title")


@dataclass(frozen=True, slots=True)
class SecRecentFilingRecord:
    """Validated SEC recent-filing record."""

    accession_number: str
    filing_date: str
    form: str
    primary_document: str
    report_date: str | None = None
    acceptance_datetime: str | None = None
    file_number: str | None = None
    primary_doc_description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.accession_number, "accession_number")
        _require_text(self.filing_date, "filing_date")
        _require_text(self.form, "form")
        _require_text(self.primary_document, "primary_document")


@dataclass(frozen=True, slots=True)
class SecSubmissionsResponse:
    """Validated SEC submissions response."""

    cik: int
    entity_name: str
    sic: str | None = None
    fiscal_year_end: str | None = None
    tickers: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()
    former_names: tuple[str, ...] = ()
    recent_filings: tuple[SecRecentFilingRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.cik <= 0:
            raise ValueError("cik must be a positive integer.")
        _require_text(self.entity_name, "entity_name")


SecFactValue = int | float | str


@dataclass(frozen=True, slots=True)
class SecFactObservation:
    """Validated SEC fact observation."""

    value: SecFactValue
    unit: str
    accession_number: str
    form: str
    filed_date: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    frame: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float, str)):
            raise ValueError("value must be a number or string.")
        _require_text(self.unit, "unit")
        _require_text(self.accession_number, "accession_number")
        _require_text(self.form, "form")
        _require_text(self.filed_date, "filed_date")
        if self.fiscal_year is not None and self.fiscal_year <= 0:
            raise ValueError("fiscal_year must be positive when provided.")


@dataclass(frozen=True, slots=True)
class SecFactConcept:
    """Validated SEC fact concept with all observations flattened."""

    taxonomy: str
    concept: str
    observations: tuple[SecFactObservation, ...]
    label: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.taxonomy, "taxonomy")
        _require_text(self.concept, "concept")
        if not self.observations:
            raise ValueError("observations must not be empty.")


@dataclass(frozen=True, slots=True)
class SecCompanyFactsResponse:
    """Validated SEC company-facts response."""

    cik: int
    entity_name: str
    concepts: tuple[SecFactConcept, ...]

    def __post_init__(self) -> None:
        if self.cik <= 0:
            raise ValueError("cik must be a positive integer.")
        _require_text(self.entity_name, "entity_name")
