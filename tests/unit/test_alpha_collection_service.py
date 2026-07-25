"""Unit tests for Alpha Vantage collection orchestration."""

from __future__ import annotations

import unittest

from app.clients.alpha_dtos import (
    AlphaVantageBalanceSheetEntry,
    AlphaVantageBalanceSheetResponse,
    AlphaVantageCashFlowEntry,
    AlphaVantageCashFlowResponse,
    AlphaVantageGlobalQuoteResponse,
    AlphaVantageIncomeStatementEntry,
    AlphaVantageIncomeStatementResponse,
    AlphaVantageOverviewResponse,
)
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.services.alpha_collection_service import AlphaCollectionInputError, AlphaVantageCollection, collect_alpha_vantage_data


class FakeAlphaVantageClient:
    """In-memory Alpha Vantage client for offline orchestration tests."""

    def __init__(self, collection: AlphaVantageCollection) -> None:
        self.collection = collection
        self.calls: list[str] = []

    def get_overview(self, symbol: str) -> AlphaVantageOverviewResponse:
        self.calls.append(f"OVERVIEW:{symbol}")
        return self.collection.overview

    def get_income_statement(self, symbol: str) -> AlphaVantageIncomeStatementResponse:
        self.calls.append(f"INCOME_STATEMENT:{symbol}")
        return self.collection.income_statement

    def get_balance_sheet(self, symbol: str) -> AlphaVantageBalanceSheetResponse:
        self.calls.append(f"BALANCE_SHEET:{symbol}")
        return self.collection.balance_sheet

    def get_cash_flow(self, symbol: str) -> AlphaVantageCashFlowResponse:
        self.calls.append(f"CASH_FLOW:{symbol}")
        return self.collection.cash_flow

    def get_global_quote(self, symbol: str) -> AlphaVantageGlobalQuoteResponse:
        self.calls.append(f"GLOBAL_QUOTE:{symbol}")
        return self.collection.global_quote


class AlphaVantageCollectionServiceTests(unittest.TestCase):
    """Offline tests for Alpha Vantage collection orchestration."""

    def setUp(self) -> None:
        self.resolved_company = ResolvedCompany(company_name="Apple Inc.", ticker="aapl")
        self.runtime_config = RuntimeConfig(alpha_vantage_api_key="demo")
        self.collection = AlphaVantageCollection(
            symbol="AAPL",
            overview=AlphaVantageOverviewResponse(
                symbol="AAPL",
                name="Apple Inc.",
                latest_quarter="2024-12-31",
                currency="USD",
                market_capitalization=1000.0,
            ),
            income_statement=AlphaVantageIncomeStatementResponse(
                symbol="AAPL",
                annual_reports=(
                    AlphaVantageIncomeStatementEntry(
                        fiscal_date_ending="2024-12-31",
                        reported_currency="USD",
                        total_revenue=100.0,
                    ),
                ),
            ),
            balance_sheet=AlphaVantageBalanceSheetResponse(
                symbol="AAPL",
                annual_reports=(
                    AlphaVantageBalanceSheetEntry(
                        fiscal_date_ending="2024-12-31",
                        reported_currency="USD",
                        total_assets=200.0,
                    ),
                ),
            ),
            cash_flow=AlphaVantageCashFlowResponse(
                symbol="AAPL",
                annual_reports=(
                    AlphaVantageCashFlowEntry(
                        fiscal_date_ending="2024-12-31",
                        reported_currency="USD",
                        operating_cash_flow=60.0,
                    ),
                ),
            ),
            global_quote=AlphaVantageGlobalQuoteResponse(
                symbol="AAPL",
                latest_trading_day="2024-12-31",
                price=200.0,
            ),
        )

    def test_collect_alpha_vantage_data_calls_each_endpoint(self) -> None:
        client = FakeAlphaVantageClient(self.collection)

        result = collect_alpha_vantage_data(self.resolved_company, client, self.runtime_config)

        self.assertEqual(
            client.calls,
            [
                "OVERVIEW:AAPL",
                "INCOME_STATEMENT:AAPL",
                "BALANCE_SHEET:AAPL",
                "CASH_FLOW:AAPL",
                "GLOBAL_QUOTE:AAPL",
            ],
        )
        self.assertEqual(result, self.collection)

    def test_collect_alpha_vantage_data_normalizes_ticker(self) -> None:
        client = FakeAlphaVantageClient(self.collection)

        collect_alpha_vantage_data(self.resolved_company, client, self.runtime_config)

        self.assertTrue(all(call.endswith(":AAPL") for call in client.calls))

    def test_collect_alpha_vantage_data_requires_ticker(self) -> None:
        client = FakeAlphaVantageClient(self.collection)
        company = ResolvedCompany(company_name="Apple Inc.")

        with self.assertRaises(AlphaCollectionInputError):
            collect_alpha_vantage_data(company, client, self.runtime_config)

    def test_collect_alpha_vantage_data_is_deterministic(self) -> None:
        client = FakeAlphaVantageClient(self.collection)

        first = collect_alpha_vantage_data(self.resolved_company, client, self.runtime_config)
        second = collect_alpha_vantage_data(self.resolved_company, client, self.runtime_config)

        self.assertEqual(first, second)
