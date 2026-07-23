"""Company resolution service for SEC-based identity matching."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Protocol

from app.clients.sec_dtos import SecTickerRecord
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.request import ResearchRequest

_LEGAL_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "ltd", "limited", "llc"}


class SecTickerClientProtocol(Protocol):
    """Minimal SEC ticker lookup contract used by company resolution."""

    def get_company_tickers(self) -> tuple[SecTickerRecord, ...]: ...


class CompanyResolutionError(Exception):
    """Base exception for company-resolution failures."""


class CompanyResolutionNoMatchError(CompanyResolutionError):
    """Raised when no candidate company can be resolved."""


class CompanyResolutionAmbiguityError(CompanyResolutionError):
    """Raised when more than one candidate remains."""


class CompanyResolutionMismatchError(CompanyResolutionError):
    """Raised when ticker and company name identify different companies."""


def resolve_company(
    request: ResearchRequest,
    runtime_config: RuntimeConfig,
    sec_client: SecTickerClientProtocol,
) -> ResolvedCompany:
    """Resolve a single public company using SEC ticker data."""

    del runtime_config

    records = sec_client.get_company_tickers()
    ticker = _normalize_ticker(request.ticker)
    company_name = request.company_name.strip() if request.company_name is not None else None

    if ticker is not None and company_name is not None:
        ticker_matches = _match_by_ticker(records, ticker)
        name_matches = _match_by_company_name(records, company_name)
        return _resolve_cross_checked_company(ticker_matches, name_matches)

    if ticker is not None:
        matches = _match_by_ticker(records, ticker)
        return _select_unique_company(matches, "ticker")

    if company_name is not None:
        matches = _match_by_company_name(records, company_name)
        return _select_unique_company(matches, "company name")

    raise CompanyResolutionNoMatchError("A ticker or company name is required.")


def normalize_sec_company_record(record: SecTickerRecord) -> ResolvedCompany:
    """Convert a validated SEC ticker record into the canonical company model."""

    return ResolvedCompany(
        company_name=record.title.strip(),
        ticker=record.ticker.strip().upper(),
        cik=f"{record.cik:010d}",
    )


def _resolve_cross_checked_company(
    ticker_matches: list[SecTickerRecord],
    name_matches: list[SecTickerRecord],
) -> ResolvedCompany:
    if not ticker_matches and not name_matches:
        raise CompanyResolutionNoMatchError("No SEC company matched the provided ticker and company name.")
    if not ticker_matches or not name_matches:
        raise CompanyResolutionMismatchError("The supplied ticker and company name do not identify the same company.")

    overlap = [record for record in ticker_matches if any(record.cik == candidate.cik for candidate in name_matches)]
    if len(overlap) == 1:
        return normalize_sec_company_record(overlap[0])
    if len(overlap) > 1:
        raise CompanyResolutionAmbiguityError("More than one SEC company remains after cross-checking the inputs.")

    raise CompanyResolutionMismatchError("The supplied ticker and company name identify different companies.")


def _select_unique_company(matches: list[SecTickerRecord], match_type: str) -> ResolvedCompany:
    if not matches:
        raise CompanyResolutionNoMatchError(f"No SEC company matched the supplied {match_type}.")
    if len(matches) > 1:
        raise CompanyResolutionAmbiguityError(f"More than one SEC company matched the supplied {match_type}.")
    return normalize_sec_company_record(matches[0])


def _match_by_ticker(records: Iterable[SecTickerRecord], supplied_ticker: str) -> list[SecTickerRecord]:
    return [record for record in records if _normalize_ticker(record.ticker) == supplied_ticker]


def _match_by_company_name(records: Iterable[SecTickerRecord], supplied_company_name: str) -> list[SecTickerRecord]:
    exact_matches = [
        record
        for record in records
        if _normalize_company_name(record.title) == _normalize_company_name(supplied_company_name)
    ]
    if exact_matches:
        return exact_matches

    conservative_name = _normalize_company_name_with_suffix_handling(supplied_company_name)
    conservative_matches = [
        record
        for record in records
        if _normalize_company_name_with_suffix_handling(record.title) == conservative_name
    ]
    return conservative_matches


def _normalize_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def _normalize_company_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^0-9a-z]+", " ", normalized)
    return " ".join(normalized.split())


def _normalize_company_name_with_suffix_handling(value: str) -> str:
    tokens = _normalize_company_name(value).split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)
