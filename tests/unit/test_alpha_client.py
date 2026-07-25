"""Unit tests for the Alpha Vantage client."""

from __future__ import annotations

import unittest

import httpx

from app.clients.alpha_vantage_client import (
    AlphaVantageAuthenticationError,
    AlphaVantageClient,
    AlphaVantageConfigurationError,
    AlphaVantageRateLimitError,
    AlphaVantageResponseValidationError,
    AlphaVantageTimeoutError,
    AlphaVantageTransportError,
)
from app.models.execution import RuntimeConfig


class AlphaVantageClientTests(unittest.TestCase):
    """Offline tests for Alpha Vantage transport and validation."""

    def _build_client(
        self,
        handler,
        *,
        api_key: str | None = "demo",
        max_retries: int = 0,
        timeout_seconds: float = 1.0,
    ) -> AlphaVantageClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(alpha_vantage_api_key=api_key, max_retries=max_retries, timeout_seconds=timeout_seconds)
        return AlphaVantageClient(runtime_config=runtime_config, http_client=http_client)

    def test_overview_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/query")
            self.assertEqual(request.url.params["function"], "OVERVIEW")
            self.assertEqual(request.url.params["symbol"], "AAPL")
            self.assertEqual(request.url.params["apikey"], "demo")
            return httpx.Response(
                200,
                json={
                    "Symbol": "AAPL",
                    "Name": "Apple Inc.",
                    "LatestQuarter": "2024-12-31",
                    "Currency": "USD",
                    "MarketCapitalization": "1000.0",
                },
            )

        client = self._build_client(handler)
        response = client.get_overview("aapl")

        self.assertEqual(response.symbol, "AAPL")
        self.assertEqual(response.name, "Apple Inc.")
        self.assertEqual(response.market_capitalization, 1000.0)

    def test_income_statement_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "annualReports": [
                        {
                            "fiscalDateEnding": "2024-12-31",
                            "reportedCurrency": "USD",
                            "totalRevenue": "100.0",
                            "grossProfit": "50.0",
                            "operatingIncome": "25.0",
                            "netIncome": "20.0",
                        }
                    ],
                    "quarterlyReports": [],
                },
            )

        client = self._build_client(handler)
        response = client.get_income_statement("AAPL")

        self.assertEqual(response.annual_reports[0].total_revenue, 100.0)
        self.assertEqual(response.annual_reports[0].reported_currency, "USD")

    def test_balance_sheet_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "annualReports": [
                        {
                            "fiscalDateEnding": "2024-12-31",
                            "reportedCurrency": "USD",
                            "totalAssets": "200.0",
                            "totalLiabilities": "80.0",
                            "totalShareholderEquity": "120.0",
                        }
                    ],
                },
            )

        client = self._build_client(handler)
        response = client.get_balance_sheet("AAPL")

        self.assertEqual(response.annual_reports[0].total_assets, 200.0)

    def test_cash_flow_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "annualReports": [
                        {
                            "fiscalDateEnding": "2024-12-31",
                            "reportedCurrency": "USD",
                            "operatingCashflow": "60.0",
                            "capitalExpenditures": "10.0",
                        }
                    ],
                },
            )

        client = self._build_client(handler)
        response = client.get_cash_flow("AAPL")

        self.assertEqual(response.annual_reports[0].operating_cash_flow, 60.0)

    def test_global_quote_request_maps_to_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "Global Quote": {
                        "01. symbol": "AAPL",
                        "02. open": "198.0",
                        "03. high": "202.0",
                        "04. low": "197.0",
                        "05. price": "200.0",
                        "06. volume": "1000000",
                        "07. latest trading day": "2024-12-31",
                        "08. previous close": "199.0",
                        "09. change": "1.0",
                        "10. change percent": "0.5%",
                    }
                },
            )

        client = self._build_client(handler)
        response = client.get_global_quote("AAPL")

        self.assertEqual(response.price, 200.0)
        self.assertEqual(response.volume, 1000000)

    def test_missing_api_key_raises_configuration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = self._build_client(handler, api_key=None)

        with self.assertRaises(AlphaVantageConfigurationError):
            client.get_overview("AAPL")

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(AlphaVantageTimeoutError):
            client.get_overview("AAPL")

    def test_rate_limit_response_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is ..."})

        client = self._build_client(handler)

        with self.assertRaises(AlphaVantageRateLimitError):
            client.get_overview("AAPL")

    def test_authentication_response_raises_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        client = self._build_client(handler)

        with self.assertRaises(AlphaVantageAuthenticationError):
            client.get_overview("AAPL")

    def test_malformed_payload_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Symbol": "AAPL"})

        client = self._build_client(handler)

        with self.assertRaises(AlphaVantageResponseValidationError):
            client.get_overview("AAPL")

    def test_non_success_http_status_raises_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="error")

        client = self._build_client(handler)

        with self.assertRaises(AlphaVantageTransportError):
            client.get_overview("AAPL")

