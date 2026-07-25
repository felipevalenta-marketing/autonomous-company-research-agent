"""Application-service orchestration for Alpha Vantage collection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.clients.alpha_dtos import (
    AlphaVantageBalanceSheetResponse,
    AlphaVantageCashFlowResponse,
    AlphaVantageGlobalQuoteResponse,
    AlphaVantageIncomeStatementResponse,
    AlphaVantageOverviewResponse,
)
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig


class AlphaCollectionError(Exception):
    """Base exception for Alpha Vantage collection failures."""


class AlphaCollectionInputError(AlphaCollectionError):
    """Raised when the Alpha Vantage collection service receives invalid input."""


class AlphaVantageCollectionClient(Protocol):
    """Narrow Alpha Vantage client contract required by collection."""

    def get_overview(self, symbol: str) -> AlphaVantageOverviewResponse:
        """Return the validated overview response."""

    def get_income_statement(self, symbol: str) -> AlphaVantageIncomeStatementResponse:
        """Return the validated income statement response."""

    def get_balance_sheet(self, symbol: str) -> AlphaVantageBalanceSheetResponse:
        """Return the validated balance sheet response."""

    def get_cash_flow(self, symbol: str) -> AlphaVantageCashFlowResponse:
        """Return the validated cash flow response."""

    def get_global_quote(self, symbol: str) -> AlphaVantageGlobalQuoteResponse:
        """Return the validated global quote response."""


@dataclass(frozen=True, slots=True)
class AlphaVantageCollection:
    """Aggregated Alpha Vantage DTO bundle."""

    symbol: str
    overview: AlphaVantageOverviewResponse
    income_statement: AlphaVantageIncomeStatementResponse
    balance_sheet: AlphaVantageBalanceSheetResponse
    cash_flow: AlphaVantageCashFlowResponse
    global_quote: AlphaVantageGlobalQuoteResponse


def collect_alpha_vantage_data(
    resolved_company: ResolvedCompany,
    alpha_client: AlphaVantageCollectionClient,
    runtime_config: RuntimeConfig | None = None,
) -> AlphaVantageCollection:
    """Collect the Alpha Vantage DTO bundle for a resolved company."""

    del runtime_config

    symbol = _require_symbol(resolved_company)
    overview = alpha_client.get_overview(symbol)
    income_statement = alpha_client.get_income_statement(symbol)
    balance_sheet = alpha_client.get_balance_sheet(symbol)
    cash_flow = alpha_client.get_cash_flow(symbol)
    global_quote = alpha_client.get_global_quote(symbol)
    return AlphaVantageCollection(
        symbol=symbol,
        overview=overview,
        income_statement=income_statement,
        balance_sheet=balance_sheet,
        cash_flow=cash_flow,
        global_quote=global_quote,
    )


def _require_symbol(resolved_company: ResolvedCompany) -> str:
    ticker = resolved_company.ticker
    if ticker is None or not ticker.strip():
        raise AlphaCollectionInputError("Resolved company must include a ticker for Alpha Vantage.")
    return ticker.strip().upper()
