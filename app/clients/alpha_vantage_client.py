"""Alpha Vantage client for deterministic financial data retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

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
from app.config.constants import PROJECT_NAME
from app.models.execution import RuntimeConfig

ALPHA_VANTAGE_QUERY_URL = "https://www.alphavantage.co/query"


class AlphaVantageClientError(Exception):
    """Base exception for Alpha Vantage client failures."""


class AlphaVantageConfigurationError(AlphaVantageClientError):
    """Raised when Alpha Vantage configuration is missing or invalid."""


class AlphaVantageAuthenticationError(AlphaVantageClientError):
    """Raised when Alpha Vantage rejects the configured credentials."""


class AlphaVantageTransportError(AlphaVantageClientError):
    """Raised when Alpha Vantage transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AlphaVantageTimeoutError(AlphaVantageTransportError):
    """Raised when Alpha Vantage requests time out."""


class AlphaVantageRateLimitError(AlphaVantageTransportError):
    """Raised when Alpha Vantage rate limiting is encountered."""


class AlphaVantageResponseValidationError(AlphaVantageClientError):
    """Raised when an Alpha Vantage payload does not match the expected shape."""


class AlphaVantageOverviewPayloadError(AlphaVantageResponseValidationError):
    """Raised when the overview payload is malformed."""


class AlphaVantageStatementPayloadError(AlphaVantageResponseValidationError):
    """Raised when a financial statement payload is malformed."""


class AlphaVantageQuotePayloadError(AlphaVantageResponseValidationError):
    """Raised when the global quote payload is malformed."""


class AlphaVantageClient:
    """Synchronous Alpha Vantage client."""

    def __init__(self, runtime_config: RuntimeConfig, http_client: httpx.Client | None = None) -> None:
        self._runtime_config = runtime_config
        self._http_client = http_client or httpx.Client()

    def get_overview(self, symbol: str) -> AlphaVantageOverviewResponse:
        payload = self._fetch_json("OVERVIEW", symbol)
        return _parse_overview_payload(payload, _normalize_symbol(symbol))

    def get_income_statement(self, symbol: str) -> AlphaVantageIncomeStatementResponse:
        payload = self._fetch_json("INCOME_STATEMENT", symbol)
        return _parse_income_statement_payload(payload, _normalize_symbol(symbol))

    def get_balance_sheet(self, symbol: str) -> AlphaVantageBalanceSheetResponse:
        payload = self._fetch_json("BALANCE_SHEET", symbol)
        return _parse_balance_sheet_payload(payload, _normalize_symbol(symbol))

    def get_cash_flow(self, symbol: str) -> AlphaVantageCashFlowResponse:
        payload = self._fetch_json("CASH_FLOW", symbol)
        return _parse_cash_flow_payload(payload, _normalize_symbol(symbol))

    def get_global_quote(self, symbol: str) -> AlphaVantageGlobalQuoteResponse:
        payload = self._fetch_json("GLOBAL_QUOTE", symbol)
        return _parse_global_quote_payload(payload, _normalize_symbol(symbol))

    def _fetch_json(self, function: str, symbol: str) -> Any:
        api_key = self._runtime_config.alpha_vantage_api_key
        if api_key is None or not api_key.strip():
            raise AlphaVantageConfigurationError("ALPHA_VANTAGE_API_KEY must be configured.")

        normalized_symbol = _normalize_symbol(symbol)
        params = {
            "function": function,
            "symbol": normalized_symbol,
            "apikey": api_key.strip(),
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": PROJECT_NAME,
        }

        attempts = self._runtime_config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http_client.get(
                    ALPHA_VANTAGE_QUERY_URL,
                    params=params,
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise AlphaVantageTimeoutError("Alpha Vantage request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise AlphaVantageTransportError("Alpha Vantage request failed.") from exc
                continue

            if response.status_code == 429:
                raise AlphaVantageRateLimitError("Alpha Vantage request was rate limited.", status_code=429)
            if response.status_code in {401, 403}:
                raise AlphaVantageAuthenticationError("Alpha Vantage rejected the configured credentials.")
            if response.status_code < 200 or response.status_code >= 300:
                raise AlphaVantageTransportError(
                    "Alpha Vantage request returned a non-success status.",
                    status_code=response.status_code,
                )

            payload = self._decode_json(response)
            _raise_for_provider_message(payload, function)
            return payload

        raise AlphaVantageTransportError("Alpha Vantage request failed after retries.")

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise AlphaVantageResponseValidationError("Alpha Vantage response was not valid JSON.") from exc


def _parse_overview_payload(payload: Any, symbol: str) -> AlphaVantageOverviewResponse:
    if not isinstance(payload, Mapping):
        raise AlphaVantageOverviewPayloadError("Alpha Vantage overview response must be a JSON object.")

    response_symbol = _require_text(payload.get("Symbol"), "Symbol", AlphaVantageOverviewPayloadError)
    if _normalize_symbol(response_symbol) != symbol:
        raise AlphaVantageOverviewPayloadError("Alpha Vantage overview symbol did not match the request.")

    return AlphaVantageOverviewResponse(
        symbol=symbol,
        name=_require_text(payload.get("Name"), "Name", AlphaVantageOverviewPayloadError),
        latest_quarter=_require_text(payload.get("LatestQuarter"), "LatestQuarter", AlphaVantageOverviewPayloadError),
        currency=_optional_text(payload.get("Currency")),
        exchange=_optional_text(payload.get("Exchange")),
        country=_optional_text(payload.get("Country")),
        sector=_optional_text(payload.get("Sector")),
        industry=_optional_text(payload.get("Industry")),
        market_capitalization=_optional_float(payload.get("MarketCapitalization")),
        description=_optional_text(payload.get("Description")),
    )


def _parse_income_statement_payload(payload: Any, symbol: str) -> AlphaVantageIncomeStatementResponse:
    if not isinstance(payload, Mapping):
        raise AlphaVantageStatementPayloadError("Alpha Vantage income-statement response must be a JSON object.")
    _validate_statement_symbol(payload, symbol, AlphaVantageStatementPayloadError)

    annual_reports = _parse_income_reports(payload.get("annualReports"), AlphaVantageStatementPayloadError)
    quarterly_reports = _parse_income_reports_optional(payload.get("quarterlyReports"), AlphaVantageStatementPayloadError)
    return AlphaVantageIncomeStatementResponse(symbol=symbol, annual_reports=annual_reports, quarterly_reports=quarterly_reports)


def _parse_balance_sheet_payload(payload: Any, symbol: str) -> AlphaVantageBalanceSheetResponse:
    if not isinstance(payload, Mapping):
        raise AlphaVantageStatementPayloadError("Alpha Vantage balance-sheet response must be a JSON object.")
    _validate_statement_symbol(payload, symbol, AlphaVantageStatementPayloadError)

    annual_reports = _parse_balance_reports(payload.get("annualReports"), AlphaVantageStatementPayloadError)
    quarterly_reports = _parse_balance_reports_optional(payload.get("quarterlyReports"), AlphaVantageStatementPayloadError)
    return AlphaVantageBalanceSheetResponse(symbol=symbol, annual_reports=annual_reports, quarterly_reports=quarterly_reports)


def _parse_cash_flow_payload(payload: Any, symbol: str) -> AlphaVantageCashFlowResponse:
    if not isinstance(payload, Mapping):
        raise AlphaVantageStatementPayloadError("Alpha Vantage cash-flow response must be a JSON object.")
    _validate_statement_symbol(payload, symbol, AlphaVantageStatementPayloadError)

    annual_reports = _parse_cash_flow_reports(payload.get("annualReports"), AlphaVantageStatementPayloadError)
    quarterly_reports = _parse_cash_flow_reports_optional(payload.get("quarterlyReports"), AlphaVantageStatementPayloadError)
    return AlphaVantageCashFlowResponse(symbol=symbol, annual_reports=annual_reports, quarterly_reports=quarterly_reports)


def _parse_global_quote_payload(payload: Any, symbol: str) -> AlphaVantageGlobalQuoteResponse:
    if not isinstance(payload, Mapping):
        raise AlphaVantageQuotePayloadError("Alpha Vantage global quote response must be a JSON object.")

    quote = payload.get("Global Quote")
    if not isinstance(quote, Mapping) or not quote:
        raise AlphaVantageQuotePayloadError("Alpha Vantage global quote payload must include a Global Quote object.")

    response_symbol = _require_text(quote.get("01. symbol"), "01. symbol", AlphaVantageQuotePayloadError)
    if _normalize_symbol(response_symbol) != symbol:
        raise AlphaVantageQuotePayloadError("Alpha Vantage global quote symbol did not match the request.")

    return AlphaVantageGlobalQuoteResponse(
        symbol=symbol,
        latest_trading_day=_require_text(quote.get("07. latest trading day"), "07. latest trading day", AlphaVantageQuotePayloadError),
        price=_require_float(quote.get("05. price"), "05. price", AlphaVantageQuotePayloadError),
        open=_optional_float(quote.get("02. open")),
        high=_optional_float(quote.get("03. high")),
        low=_optional_float(quote.get("04. low")),
        volume=_optional_int(quote.get("06. volume")),
        previous_close=_optional_float(quote.get("08. previous close")),
        change=_optional_float(quote.get("09. change")),
        change_percent=_optional_percent(quote.get("10. change percent")),
    )


def _parse_income_reports(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageIncomeStatementEntry, ...]:
    return tuple(_parse_income_report(entry, error_type) for entry in _require_report_list(value, error_type, required=True))


def _parse_income_reports_optional(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageIncomeStatementEntry, ...]:
    return tuple(_parse_income_report(entry, error_type) for entry in _require_report_list(value, error_type, required=False))


def _parse_balance_reports(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageBalanceSheetEntry, ...]:
    return tuple(_parse_balance_report(entry, error_type) for entry in _require_report_list(value, error_type, required=True))


def _parse_balance_reports_optional(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageBalanceSheetEntry, ...]:
    return tuple(_parse_balance_report(entry, error_type) for entry in _require_report_list(value, error_type, required=False))


def _parse_cash_flow_reports(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageCashFlowEntry, ...]:
    return tuple(_parse_cash_flow_report(entry, error_type) for entry in _require_report_list(value, error_type, required=True))


def _parse_cash_flow_reports_optional(value: Any, error_type: type[Exception]) -> tuple[AlphaVantageCashFlowEntry, ...]:
    return tuple(_parse_cash_flow_report(entry, error_type) for entry in _require_report_list(value, error_type, required=False))


def _require_report_list(value: Any, error_type: type[Exception], *, required: bool) -> list[Mapping[str, Any]]:
    if value is None:
        if required:
            raise error_type("Alpha Vantage statement response requires a non-empty report list.")
        return []
    if not isinstance(value, list):
        raise error_type("Alpha Vantage statement response requires a report list.")
    if required and not value:
        raise error_type("Alpha Vantage statement response requires a non-empty report list.")
    reports: list[Mapping[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise error_type("Alpha Vantage report entry must be a JSON object.")
        reports.append(entry)
    return reports


def _parse_income_report(entry: Mapping[str, Any], error_type: type[Exception]) -> AlphaVantageIncomeStatementEntry:
    return AlphaVantageIncomeStatementEntry(
        fiscal_date_ending=_require_text(entry.get("fiscalDateEnding"), "fiscalDateEnding", error_type),
        reported_currency=_optional_text(entry.get("reportedCurrency")),
        total_revenue=_optional_float(entry.get("totalRevenue")),
        gross_profit=_optional_float(entry.get("grossProfit")),
        operating_income=_optional_float(entry.get("operatingIncome")),
        net_income=_optional_float(entry.get("netIncome")),
        operating_expenses=_optional_float(entry.get("operatingExpenses")),
        diluted_eps=_optional_float(entry.get("dilutedEPS")),
    )


def _parse_balance_report(entry: Mapping[str, Any], error_type: type[Exception]) -> AlphaVantageBalanceSheetEntry:
    return AlphaVantageBalanceSheetEntry(
        fiscal_date_ending=_require_text(entry.get("fiscalDateEnding"), "fiscalDateEnding", error_type),
        reported_currency=_optional_text(entry.get("reportedCurrency")),
        total_assets=_optional_float(entry.get("totalAssets")),
        total_liabilities=_optional_float(entry.get("totalLiabilities")),
        total_shareholder_equity=_optional_float(entry.get("totalShareholderEquity")),
        cash_and_cash_equivalents_at_carrying_value=_optional_float(entry.get("cashAndCashEquivalentsAtCarryingValue")),
        current_assets=_optional_float(entry.get("currentAssets")),
        current_liabilities=_optional_float(entry.get("currentLiabilities")),
    )


def _parse_cash_flow_report(entry: Mapping[str, Any], error_type: type[Exception]) -> AlphaVantageCashFlowEntry:
    return AlphaVantageCashFlowEntry(
        fiscal_date_ending=_require_text(entry.get("fiscalDateEnding"), "fiscalDateEnding", error_type),
        reported_currency=_optional_text(entry.get("reportedCurrency")),
        operating_cash_flow=_optional_float(entry.get("operatingCashflow")),
        capital_expenditures=_optional_float(entry.get("capitalExpenditures")),
        dividend_payout=_optional_float(entry.get("dividendPayout")),
        free_cash_flow=_optional_float(entry.get("freeCashFlow")),
    )


def _validate_statement_symbol(payload: Mapping[str, Any], symbol: str, error_type: type[Exception]) -> None:
    response_symbol = payload.get("symbol")
    if not isinstance(response_symbol, str) or not response_symbol.strip():
        raise error_type("Alpha Vantage statement response requires a symbol.")
    if _normalize_symbol(response_symbol) != symbol:
        raise error_type("Alpha Vantage statement symbol did not match the request.")


def _raise_for_provider_message(payload: Any, function: str) -> None:
    if not isinstance(payload, Mapping):
        return

    note = payload.get("Note")
    if isinstance(note, str) and note.strip():
        raise AlphaVantageRateLimitError(note.strip())

    error_message = payload.get("Error Message")
    if isinstance(error_message, str) and error_message.strip():
        raise AlphaVantageAuthenticationError(error_message.strip())

    information = payload.get("Information")
    if isinstance(information, str) and information.strip():
        message = information.strip()
        lowered = message.lower()
        if "frequency" in lowered or "rate limit" in lowered:
            raise AlphaVantageRateLimitError(message)
        if "invalid api call" in lowered or "apikey" in lowered or "api key" in lowered:
            raise AlphaVantageAuthenticationError(message)
        raise AlphaVantageResponseValidationError(f"Alpha Vantage {function} response reported an informational message.")


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise AlphaVantageConfigurationError("Alpha Vantage symbol must be a non-empty string.")
    return symbol.strip().upper()


def _require_text(
    value: Any,
    field_name: str,
    error_type: type[Exception] = AlphaVantageResponseValidationError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"Alpha Vantage payload requires a non-empty {field_name} value.")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        if stripped.endswith("%"):
            stripped = stripped[:-1]
        try:
            return float(stripped)
        except ValueError as exc:
            raise AlphaVantageResponseValidationError("Alpha Vantage payload field must be numeric when provided.") from exc
    raise AlphaVantageResponseValidationError("Alpha Vantage payload field must be numeric when provided.")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        try:
            return int(float(stripped))
        except ValueError as exc:
            raise AlphaVantageResponseValidationError("Alpha Vantage payload field must be an integer when provided.") from exc
    raise AlphaVantageResponseValidationError("Alpha Vantage payload field must be an integer when provided.")


def _require_float(value: Any, field_name: str, error_type: type[Exception]) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise error_type(f"Alpha Vantage payload requires a non-empty {field_name} value.")
    return parsed


def _optional_percent(value: Any) -> float | None:
    parsed = _optional_text(value)
    if parsed is None:
        return None
    if parsed.endswith("%"):
        parsed = parsed[:-1]
    try:
        return float(parsed)
    except ValueError as exc:
        raise AlphaVantageResponseValidationError("Alpha Vantage percentage field must be numeric when provided.") from exc
