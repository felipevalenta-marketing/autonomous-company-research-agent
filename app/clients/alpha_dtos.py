"""Alpha Vantage provider-specific DTOs."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_positive_float(value: float | None, field_name: str) -> float:
    if value is None:
        raise ValueError(f"{field_name} must not be empty.")
    if value < 0:
        raise ValueError(f"{field_name} must be zero or positive.")
    return value


def _require_positive_int(value: int | None, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} must not be empty.")
    if value < 0:
        raise ValueError(f"{field_name} must be zero or positive.")
    return value


@dataclass(frozen=True, slots=True)
class AlphaVantageOverviewResponse:
    """Validated Alpha Vantage company overview response."""

    symbol: str
    name: str
    latest_quarter: str
    currency: str | None = None
    exchange: str | None = None
    country: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_capitalization: float | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.symbol, "symbol")
        _require_text(self.name, "name")
        _require_text(self.latest_quarter, "latest_quarter")
        if self.market_capitalization is not None and self.market_capitalization < 0:
            raise ValueError("market_capitalization must be zero or positive.")


@dataclass(frozen=True, slots=True)
class AlphaVantageIncomeStatementEntry:
    """Validated Alpha Vantage income statement report entry."""

    fiscal_date_ending: str
    reported_currency: str | None = None
    total_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_expenses: float | None = None
    diluted_eps: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.fiscal_date_ending, "fiscal_date_ending")


@dataclass(frozen=True, slots=True)
class AlphaVantageIncomeStatementResponse:
    """Validated Alpha Vantage income statement response."""

    symbol: str
    annual_reports: tuple[AlphaVantageIncomeStatementEntry, ...]
    quarterly_reports: tuple[AlphaVantageIncomeStatementEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.symbol, "symbol")
        if not self.annual_reports:
            raise ValueError("annual_reports must not be empty.")


@dataclass(frozen=True, slots=True)
class AlphaVantageBalanceSheetEntry:
    """Validated Alpha Vantage balance sheet report entry."""

    fiscal_date_ending: str
    reported_currency: str | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_shareholder_equity: float | None = None
    cash_and_cash_equivalents_at_carrying_value: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.fiscal_date_ending, "fiscal_date_ending")


@dataclass(frozen=True, slots=True)
class AlphaVantageBalanceSheetResponse:
    """Validated Alpha Vantage balance sheet response."""

    symbol: str
    annual_reports: tuple[AlphaVantageBalanceSheetEntry, ...]
    quarterly_reports: tuple[AlphaVantageBalanceSheetEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.symbol, "symbol")
        if not self.annual_reports:
            raise ValueError("annual_reports must not be empty.")


@dataclass(frozen=True, slots=True)
class AlphaVantageCashFlowEntry:
    """Validated Alpha Vantage cash flow report entry."""

    fiscal_date_ending: str
    reported_currency: str | None = None
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    dividend_payout: float | None = None
    free_cash_flow: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.fiscal_date_ending, "fiscal_date_ending")


@dataclass(frozen=True, slots=True)
class AlphaVantageCashFlowResponse:
    """Validated Alpha Vantage cash flow response."""

    symbol: str
    annual_reports: tuple[AlphaVantageCashFlowEntry, ...]
    quarterly_reports: tuple[AlphaVantageCashFlowEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.symbol, "symbol")
        if not self.annual_reports:
            raise ValueError("annual_reports must not be empty.")


@dataclass(frozen=True, slots=True)
class AlphaVantageGlobalQuoteResponse:
    """Validated Alpha Vantage global quote response."""

    symbol: str
    latest_trading_day: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.symbol, "symbol")
        _require_text(self.latest_trading_day, "latest_trading_day")
        _require_positive_float(self.price, "price")
        if self.volume is not None:
            _require_positive_int(self.volume, "volume")
