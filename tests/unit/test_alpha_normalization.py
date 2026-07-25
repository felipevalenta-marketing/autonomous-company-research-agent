"""Unit tests for Alpha Vantage normalization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

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
from app.services.alpha_collection_service import AlphaVantageCollection
from app.services.alpha_normalization_service import normalize_alpha_vantage_data


class AlphaVantageNormalizationTests(unittest.TestCase):
    """Offline tests for Alpha Vantage normalization."""

    def setUp(self) -> None:
        self.company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL")
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
                        gross_profit=50.0,
                        operating_income=25.0,
                        net_income=20.0,
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
                        total_liabilities=80.0,
                        total_shareholder_equity=120.0,
                        cash_and_cash_equivalents_at_carrying_value=40.0,
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
                        capital_expenditures=10.0,
                    ),
                ),
            ),
            global_quote=AlphaVantageGlobalQuoteResponse(
                symbol="AAPL",
                latest_trading_day="2024-12-31",
                price=200.0,
                open=198.0,
                high=202.0,
                low=197.0,
                volume=1000000,
                previous_close=199.0,
                change=1.0,
                change_percent=0.5,
            ),
        )

    def test_normalization_returns_financial_metrics_and_sources(self) -> None:
        result = normalize_alpha_vantage_data(self.company, self.collection)

        self.assertEqual(len(result.financial_metrics), 15)
        self.assertGreaterEqual(len(result.sources), 5)
        self.assertEqual(result.financial_metrics[0].metric_name, "Market Capitalization")
        self.assertEqual(result.financial_metrics[0].currency, "USD")
        self.assertEqual(result.financial_metrics[1].metric_name, "Revenue")
        json.dumps(asdict(result))

    def test_normalization_is_deterministic(self) -> None:
        first = normalize_alpha_vantage_data(self.company, self.collection)
        second = normalize_alpha_vantage_data(self.company, self.collection)

        self.assertEqual(first, second)

    def test_normalization_preserves_source_urls_and_periods(self) -> None:
        result = normalize_alpha_vantage_data(self.company, self.collection)

        self.assertTrue(all(source.source_url.startswith("https://www.alphavantage.co/query?") for source in result.sources))
        self.assertTrue(all(metric.period for metric in result.financial_metrics))
