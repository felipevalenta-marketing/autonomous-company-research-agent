"""Unit tests for Alpha Vantage DTOs."""

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


class AlphaVantageDtoTests(unittest.TestCase):
    """Offline DTO validation and serialization tests."""

    def test_overview_dto_is_serializable(self) -> None:
        dto = AlphaVantageOverviewResponse(
            symbol="AAPL",
            name="Apple Inc.",
            latest_quarter="2024-12-31",
            currency="USD",
            market_capitalization=1000.0,
        )
        json.dumps(asdict(dto))

    def test_overview_rejects_blank_symbol(self) -> None:
        with self.assertRaises(ValueError):
            AlphaVantageOverviewResponse(symbol="", name="Apple Inc.", latest_quarter="2024-12-31")

    def test_income_statement_response_is_serializable(self) -> None:
        dto = AlphaVantageIncomeStatementResponse(
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
        )
        json.dumps(asdict(dto))

    def test_balance_sheet_response_is_serializable(self) -> None:
        dto = AlphaVantageBalanceSheetResponse(
            symbol="AAPL",
            annual_reports=(
                AlphaVantageBalanceSheetEntry(
                    fiscal_date_ending="2024-12-31",
                    reported_currency="USD",
                    total_assets=200.0,
                    total_liabilities=80.0,
                    total_shareholder_equity=120.0,
                ),
            ),
        )
        json.dumps(asdict(dto))

    def test_cash_flow_response_is_serializable(self) -> None:
        dto = AlphaVantageCashFlowResponse(
            symbol="AAPL",
            annual_reports=(
                AlphaVantageCashFlowEntry(
                    fiscal_date_ending="2024-12-31",
                    reported_currency="USD",
                    operating_cash_flow=60.0,
                    capital_expenditures=10.0,
                ),
            ),
        )
        json.dumps(asdict(dto))

    def test_global_quote_response_is_serializable(self) -> None:
        dto = AlphaVantageGlobalQuoteResponse(
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
        )
        json.dumps(asdict(dto))

    def test_statement_response_requires_reports(self) -> None:
        with self.assertRaises(ValueError):
            AlphaVantageIncomeStatementResponse(symbol="AAPL", annual_reports=())

