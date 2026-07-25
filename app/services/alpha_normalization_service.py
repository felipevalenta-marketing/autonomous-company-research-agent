"""Alpha Vantage normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.clients.alpha_dtos import (
    AlphaVantageBalanceSheetEntry,
    AlphaVantageCashFlowEntry,
    AlphaVantageIncomeStatementEntry,
    AlphaVantageOverviewResponse,
)
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.providers import FinancialMetric
from app.models.sources import SourceRecord
from app.services.alpha_collection_service import AlphaVantageCollection
from app.utils.hashing import sha256_text

ALPHA_VANTAGE_PROVIDER_NAME = "Alpha Vantage"


@dataclass(frozen=True, slots=True)
class AlphaNormalizationResult:
    """Canonical Alpha Vantage normalization output."""

    financial_metrics: tuple[FinancialMetric, ...]
    sources: tuple[SourceRecord, ...]


def normalize_alpha_vantage_data(
    resolved_company: ResolvedCompany,
    collection: AlphaVantageCollection,
    runtime_config: RuntimeConfig | None = None,
) -> AlphaNormalizationResult:
    """Convert Alpha Vantage DTOs into canonical financial records."""

    del runtime_config

    metrics: list[FinancialMetric] = []
    sources: list[SourceRecord] = []
    seen_metric_ids: set[str] = set()
    seen_source_ids: set[str] = set()

    overview_source = _build_source_record(
        resolved_company=resolved_company,
        symbol=collection.symbol,
        endpoint="OVERVIEW",
        acquired_at=collection.overview.latest_quarter,
        raw_reference=collection.overview.latest_quarter,
        source_url=_build_source_url("OVERVIEW", collection.symbol),
    )
    _append_source(sources, seen_source_ids, overview_source)
    if collection.overview.market_capitalization is not None:
        _append_metric(
            metrics,
            seen_metric_ids,
            FinancialMetric(
                metric_id=_build_metric_id(resolved_company, "OVERVIEW", "Market Capitalization", collection.overview.latest_quarter),
                company_name=resolved_company.company_name,
                metric_name="Market Capitalization",
                value=collection.overview.market_capitalization,
                period=collection.overview.latest_quarter,
                source_id=overview_source.source_id,
                currency=collection.overview.currency,
            ),
        )

    _normalize_statement_group(
        resolved_company,
        collection.symbol,
        "INCOME_STATEMENT",
        collection.income_statement.annual_reports,
        metrics,
        sources,
        seen_metric_ids,
        seen_source_ids,
        _income_statement_metrics,
    )
    _normalize_statement_group(
        resolved_company,
        collection.symbol,
        "BALANCE_SHEET",
        collection.balance_sheet.annual_reports,
        metrics,
        sources,
        seen_metric_ids,
        seen_source_ids,
        _balance_sheet_metrics,
    )
    _normalize_statement_group(
        resolved_company,
        collection.symbol,
        "CASH_FLOW",
        collection.cash_flow.annual_reports,
        metrics,
        sources,
        seen_metric_ids,
        seen_source_ids,
        _cash_flow_metrics,
    )

    quote_source = _build_source_record(
        resolved_company=resolved_company,
        symbol=collection.symbol,
        endpoint="GLOBAL_QUOTE",
        acquired_at=collection.global_quote.latest_trading_day,
        raw_reference=collection.global_quote.latest_trading_day,
        source_url=_build_source_url("GLOBAL_QUOTE", collection.symbol),
    )
    _append_source(sources, seen_source_ids, quote_source)
    _append_metric(
        metrics,
        seen_metric_ids,
        FinancialMetric(
            metric_id=_build_metric_id(resolved_company, "GLOBAL_QUOTE", "Price", collection.global_quote.latest_trading_day),
            company_name=resolved_company.company_name,
            metric_name="Price",
            value=collection.global_quote.price,
            period=collection.global_quote.latest_trading_day,
            source_id=quote_source.source_id,
            currency=None,
            unit="share",
        ),
    )
    if collection.global_quote.change is not None:
        _append_metric(
            metrics,
            seen_metric_ids,
            FinancialMetric(
                metric_id=_build_metric_id(resolved_company, "GLOBAL_QUOTE", "Change", collection.global_quote.latest_trading_day),
                company_name=resolved_company.company_name,
                metric_name="Change",
                value=collection.global_quote.change,
                period=collection.global_quote.latest_trading_day,
                source_id=quote_source.source_id,
                currency=None,
                unit="share",
            ),
        )
    if collection.global_quote.change_percent is not None:
        _append_metric(
            metrics,
            seen_metric_ids,
            FinancialMetric(
                metric_id=_build_metric_id(resolved_company, "GLOBAL_QUOTE", "Change Percent", collection.global_quote.latest_trading_day),
                company_name=resolved_company.company_name,
                metric_name="Change Percent",
                value=collection.global_quote.change_percent,
                period=collection.global_quote.latest_trading_day,
                source_id=quote_source.source_id,
                currency=None,
                unit="percent",
            ),
        )
    if collection.global_quote.volume is not None:
        _append_metric(
            metrics,
            seen_metric_ids,
            FinancialMetric(
                metric_id=_build_metric_id(resolved_company, "GLOBAL_QUOTE", "Volume", collection.global_quote.latest_trading_day),
                company_name=resolved_company.company_name,
                metric_name="Volume",
                value=float(collection.global_quote.volume),
                period=collection.global_quote.latest_trading_day,
                source_id=quote_source.source_id,
                currency=None,
                unit="shares",
            ),
        )

    return AlphaNormalizationResult(financial_metrics=tuple(metrics), sources=tuple(sources))


def _normalize_statement_group(
    resolved_company: ResolvedCompany,
    symbol: str,
    endpoint: str,
    reports: tuple[AlphaVantageIncomeStatementEntry | AlphaVantageBalanceSheetEntry | AlphaVantageCashFlowEntry, ...],
    metrics: list[FinancialMetric],
    sources: list[SourceRecord],
    seen_metric_ids: set[str],
    seen_source_ids: set[str],
    mapper,
) -> None:
    for report in reports:
        source = _build_source_record(
            resolved_company=resolved_company,
            symbol=symbol,
            endpoint=endpoint,
            acquired_at=report.fiscal_date_ending,
            raw_reference=report.fiscal_date_ending,
            source_url=_build_source_url(endpoint, symbol, report.fiscal_date_ending),
        )
        _append_source(sources, seen_source_ids, source)
        for metric_name, value, currency, unit in mapper(report):
            if value is None:
                continue
            _append_metric(
                metrics,
                seen_metric_ids,
                FinancialMetric(
                    metric_id=_build_metric_id(resolved_company, endpoint, metric_name, report.fiscal_date_ending),
                    company_name=resolved_company.company_name,
                    metric_name=metric_name,
                    value=value,
                    period=report.fiscal_date_ending,
                    source_id=source.source_id,
                    currency=currency,
                    unit=unit,
                ),
            )


def _income_statement_metrics(
    report: AlphaVantageIncomeStatementEntry,
) -> tuple[tuple[str, float | None, str | None, str | None], ...]:
    return (
        ("Revenue", report.total_revenue, report.reported_currency, None),
        ("Gross Profit", report.gross_profit, report.reported_currency, None),
        ("Operating Income", report.operating_income, report.reported_currency, None),
        ("Net Income", report.net_income, report.reported_currency, None),
    )


def _balance_sheet_metrics(
    report: AlphaVantageBalanceSheetEntry,
) -> tuple[tuple[str, float | None, str | None, str | None], ...]:
    return (
        ("Total Assets", report.total_assets, report.reported_currency, None),
        ("Total Liabilities", report.total_liabilities, report.reported_currency, None),
        ("Total Shareholder Equity", report.total_shareholder_equity, report.reported_currency, None),
        (
            "Cash and Cash Equivalents",
            report.cash_and_cash_equivalents_at_carrying_value,
            report.reported_currency,
            None,
        ),
    )


def _cash_flow_metrics(
    report: AlphaVantageCashFlowEntry,
) -> tuple[tuple[str, float | None, str | None, str | None], ...]:
    return (
        ("Operating Cash Flow", report.operating_cash_flow, report.reported_currency, None),
        ("Capital Expenditures", report.capital_expenditures, report.reported_currency, None),
    )


def _build_source_record(
    resolved_company: ResolvedCompany,
    symbol: str,
    endpoint: str,
    acquired_at: str,
    raw_reference: str | None,
    source_url: str,
) -> SourceRecord:
    acquisition_timestamp = _normalize_acquired_at(acquired_at)
    source_id = _build_source_id(resolved_company, symbol, endpoint, raw_reference or acquired_at)
    return SourceRecord(
        source_id=source_id,
        company_name=resolved_company.company_name,
        provider_name=ALPHA_VANTAGE_PROVIDER_NAME,
        authority_level="secondary",
        acquired_at=acquisition_timestamp,
        source_url=source_url,
        raw_reference=raw_reference,
        payload_type=endpoint.lower(),
    )


def _build_source_url(endpoint: str, symbol: str, report_date: str | None = None) -> str:
    query = [f"function={endpoint}", f"symbol={symbol}"]
    if report_date is not None:
        query.append(f"report_date={report_date}")
    return f"https://www.alphavantage.co/query?{'&'.join(query)}"


def _build_source_id(resolved_company: ResolvedCompany, symbol: str, endpoint: str, reference: str) -> str:
    return f"alpha_source_{sha256_text('|'.join([resolved_company.company_name, symbol, endpoint, reference]))[:16]}"


def _build_metric_id(resolved_company: ResolvedCompany, endpoint: str, metric_name: str, reference: str) -> str:
    symbol = resolved_company.ticker or ""
    return f"alpha_metric_{sha256_text('|'.join([resolved_company.company_name, symbol, endpoint, metric_name, reference]))[:16]}"


def _append_source(sources: list[SourceRecord], seen_source_ids: set[str], source: SourceRecord) -> None:
    if source.source_id in seen_source_ids:
        return
    seen_source_ids.add(source.source_id)
    sources.append(source)


def _append_metric(metrics: list[FinancialMetric], seen_metric_ids: set[str], metric: FinancialMetric) -> None:
    if metric.metric_id in seen_metric_ids:
        return
    seen_metric_ids.add(metric.metric_id)
    metrics.append(metric)


def _normalize_acquired_at(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("acquired_at must not be empty.")
    if "T" in stripped:
        return stripped
    return f"{stripped}T00:00:00Z"
