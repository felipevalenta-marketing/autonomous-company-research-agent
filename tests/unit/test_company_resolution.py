"""Unit tests for SEC-based company resolution."""

from __future__ import annotations

import unittest

from app.clients.sec_dtos import SecTickerRecord
from app.models.execution import RuntimeConfig
from app.models.request import ResearchRequest
from app.services.company_resolution_service import (
    CompanyResolutionAmbiguityError,
    CompanyResolutionMismatchError,
    CompanyResolutionNoMatchError,
    resolve_company,
)


class FakeSecClient:
    """In-memory SEC ticker lookup client for offline tests."""

    def __init__(self, records: tuple[SecTickerRecord, ...]) -> None:
        self._records = records

    def get_company_tickers(self) -> tuple[SecTickerRecord, ...]:
        return self._records


class CompanyResolutionTests(unittest.TestCase):
    """Deterministic SEC company-resolution tests."""

    def setUp(self) -> None:
        self.runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")
        self.records = (
            SecTickerRecord(cik=320193, ticker="AAPL", title="Apple Inc."),
            SecTickerRecord(cik=789019, ticker="MSFT", title="Microsoft Corporation"),
        )
        self.client = FakeSecClient(self.records)

    def test_exact_ticker_resolution(self) -> None:
        request = ResearchRequest(ticker="AAPL")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.company_name, "Apple Inc.")
        self.assertEqual(company.ticker, "AAPL")
        self.assertEqual(company.cik, "0000320193")

    def test_ticker_normalization_from_lowercase(self) -> None:
        request = ResearchRequest(ticker="aapl")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.ticker, "AAPL")

    def test_exact_company_name_resolution(self) -> None:
        request = ResearchRequest(company_name="Apple Inc.")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.company_name, "Apple Inc.")
        self.assertEqual(company.cik, "0000320193")

    def test_conservative_legal_suffix_normalization(self) -> None:
        request = ResearchRequest(company_name="Apple Incorporated")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.company_name, "Apple Inc.")
        self.assertEqual(company.ticker, "AAPL")

    def test_ticker_and_company_name_agree(self) -> None:
        request = ResearchRequest(ticker="aapl", company_name="Apple Incorporated")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.company_name, "Apple Inc.")
        self.assertEqual(company.ticker, "AAPL")

    def test_ticker_and_company_name_mismatch_raises_error(self) -> None:
        request = ResearchRequest(ticker="AAPL", company_name="Microsoft Corporation")

        with self.assertRaises(CompanyResolutionMismatchError):
            resolve_company(request, self.runtime_config, self.client)

    def test_no_match_raises_error(self) -> None:
        request = ResearchRequest(ticker="ZZZZ")

        with self.assertRaises(CompanyResolutionNoMatchError):
            resolve_company(request, self.runtime_config, self.client)

    def test_ambiguous_normalized_name_raises_error(self) -> None:
        ambiguous_client = FakeSecClient(
            (
                SecTickerRecord(cik=1, ticker="AAA", title="Acme Inc."),
                SecTickerRecord(cik=2, ticker="BBB", title="Acme Corporation"),
            )
        )
        request = ResearchRequest(company_name="Acme")

        with self.assertRaises(CompanyResolutionAmbiguityError):
            resolve_company(request, self.runtime_config, ambiguous_client)

    def test_resolution_is_deterministic(self) -> None:
        request = ResearchRequest(company_name="Apple Incorporated")

        first = resolve_company(request, self.runtime_config, self.client)
        second = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(first, second)

    def test_zero_padded_cik_is_preserved(self) -> None:
        request = ResearchRequest(ticker="AAPL")
        company = resolve_company(request, self.runtime_config, self.client)

        self.assertEqual(company.cik, "0000320193")
