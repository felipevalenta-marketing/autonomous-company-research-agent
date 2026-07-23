"""Unit tests for the SEC client."""

from __future__ import annotations

import unittest

import httpx

from app.clients.sec_client import (
    SecClient,
    SecConfigurationError,
    SecCompanyFactsPayloadError,
    SecRateLimitError,
    SecResponseValidationError,
    SecRecentFilingArrayError,
    SecSubmissionsPayloadError,
    SecUnsupportedFactValueError,
    SecTimeoutError,
    SecTransportError,
)
from app.models.execution import RuntimeConfig


class SecClientTests(unittest.TestCase):
    """Offline tests for SEC company-ticker retrieval."""

    def _build_client(self, handler, *, sec_user_agent: str | None = "Example App (dev@example.com)", max_retries: int = 0) -> SecClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        runtime_config = RuntimeConfig(sec_user_agent=sec_user_agent, max_retries=max_retries)
        return SecClient(runtime_config=runtime_config, http_client=http_client)

    def test_valid_ticker_payload_is_mapped_to_dtos(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/files/company_tickers.json")
            self.assertEqual(request.headers["User-Agent"], "Example App (dev@example.com)")
            return httpx.Response(
                200,
                json={
                    "1": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
                    "0": {"cik_str": 789019, "ticker": "msft", "title": "Microsoft Corporation"},
                },
            )

        client = self._build_client(handler)
        records = client.get_company_tickers()

        self.assertEqual([record.ticker for record in records], ["msft", "aapl"])
        self.assertEqual(records[0].cik, 789019)
        self.assertEqual(records[1].title, "Apple Inc.")
        self.assertTrue(all(hasattr(record, "ticker") for record in records))

    def test_malformed_top_level_payload_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["invalid"])

        client = self._build_client(handler)

        with self.assertRaises(SecResponseValidationError):
            client.get_company_tickers()

    def test_missing_required_record_fields_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})

        client = self._build_client(handler)

        with self.assertRaises(SecResponseValidationError):
            client.get_company_tickers()

    def test_non_success_http_status_raises_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = self._build_client(handler)

        with self.assertRaises(SecTransportError):
            client.get_company_tickers()

    def test_timeout_raises_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        client = self._build_client(handler)

        with self.assertRaises(SecTimeoutError):
            client.get_company_tickers()

    def test_rate_limit_response_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = self._build_client(handler)

        with self.assertRaises(SecRateLimitError):
            client.get_company_tickers()

    def test_missing_user_agent_configuration_raises_configuration_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = self._build_client(handler, sec_user_agent=None)

        with self.assertRaises(SecConfigurationError):
            client.get_company_tickers()

    def test_public_result_does_not_expose_raw_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})

        client = self._build_client(handler)
        records = client.get_company_tickers()

        self.assertEqual(len(records), 1)
        self.assertNotIsInstance(records[0], dict)

    def test_successful_submissions_request_returns_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/submissions/CIK0000320193.json")
            self.assertEqual(request.headers["User-Agent"], "Example App (dev@example.com)")
            return httpx.Response(
                200,
                json={
                    "cik": 320193,
                    "name": "Apple Inc.",
                    "sic": "3571",
                    "fiscalYearEnd": "0928",
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000320193-24-000010", "0000320193-24-000011"],
                            "filingDate": ["2024-11-01", "2024-08-01"],
                            "reportDate": ["2024-09-30", "2024-06-30"],
                            "acceptanceDateTime": ["2024-11-01T16:00:00Z", "2024-08-01T16:00:00Z"],
                            "form": ["10-K", "8-K"],
                            "fileNumber": ["001-00000", "001-00001"],
                            "primaryDocument": ["aapl-20240928x10k.htm", "aapl.htm"],
                            "primaryDocDescription": ["Annual report", "Current report"],
                        }
                    },
                },
            )

        client = self._build_client(handler)
        response = client.get_company_submissions(320193)

        self.assertEqual(response.entity_name, "Apple Inc.")
        self.assertEqual(len(response.recent_filings), 2)
        self.assertEqual(response.recent_filings[0].form, "10-K")
        self.assertEqual(response.recent_filings[1].primary_document, "aapl.htm")

    def test_successful_company_facts_request_returns_dto(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/xbrl/companyfacts/CIK0000320193.json")
            self.assertEqual(request.headers["User-Agent"], "Example App (dev@example.com)")
            return httpx.Response(
                200,
                json={
                    "cik": 320193,
                    "entityName": "Apple Inc.",
                    "facts": {
                        "us-gaap": {
                            "Revenues": {
                                "label": "Revenues",
                                "description": "Revenue",
                                "units": {
                                    "USD": [
                                        {
                                            "val": 100.0,
                                            "accn": "0000320193-24-000010",
                                            "fy": 2024,
                                            "fp": "FY",
                                            "form": "10-K",
                                            "filed": "2024-11-01",
                                            "frame": "CY2024",
                                            "start": "2023-10-01",
                                            "end": "2024-09-30",
                                        }
                                    ]
                                },
                            }
                        }
                    },
                },
            )

        client = self._build_client(handler)
        response = client.get_company_facts("320193")

        self.assertEqual(response.entity_name, "Apple Inc.")
        self.assertEqual(response.concepts[0].taxonomy, "us-gaap")
        self.assertEqual(response.concepts[0].observations[0].unit, "USD")

    def test_cik_is_zero_padded_in_requests(self) -> None:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            return httpx.Response(200, json={})

        client = self._build_client(handler)

        with self.assertRaises(SecSubmissionsPayloadError):
            client.get_company_submissions("320193")

        self.assertEqual(requested_paths, ["/submissions/CIK0000320193.json"])

    def test_submissions_payload_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"cik": 320193, "name": "Apple Inc.", "filings": {}})

        client = self._build_client(handler)

        with self.assertRaises(SecSubmissionsPayloadError):
            client.get_company_submissions(320193)

    def test_parallel_arrays_length_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "cik": 320193,
                    "name": "Apple Inc.",
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000320193-24-000010"],
                            "filingDate": ["2024-11-01", "2024-08-01"],
                            "form": ["10-K"],
                            "primaryDocument": ["aapl.htm"],
                        }
                    },
                },
            )

        client = self._build_client(handler)

        with self.assertRaises(SecRecentFilingArrayError):
            client.get_company_submissions(320193)

    def test_missing_required_filing_fields_raise_validation_error(self) -> None:
        cases = [
            {"accessionNumber": None, "filingDate": ["2024-11-01"], "form": ["10-K"], "primaryDocument": ["aapl.htm"]},
            {"accessionNumber": ["0000320193-24-000010"], "filingDate": ["2024-11-01"], "primaryDocument": ["aapl.htm"]},
            {"accessionNumber": ["0000320193-24-000010"], "filingDate": ["2024-11-01"], "form": ["10-K"]},
        ]

        for recent in cases:
            with self.subTest(recent=recent):
                def handler(request: httpx.Request) -> httpx.Response:
                    return httpx.Response(
                        200,
                        json={
                            "cik": 320193,
                            "name": "Apple Inc.",
                            "filings": {"recent": recent},
                        },
                    )

                client = self._build_client(handler)

                with self.assertRaises(SecSubmissionsPayloadError):
                    client.get_company_submissions(320193)

    def test_company_facts_payload_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"cik": 320193, "entityName": "Apple Inc.", "facts": {}})

        client = self._build_client(handler)

        with self.assertRaises(SecCompanyFactsPayloadError):
            client.get_company_facts(320193)

    def test_company_facts_missing_unit_and_unsupported_value_raise_validation_error(self) -> None:
        cases = [
            (
                {
                    "us-gaap": {
                        "Revenues": {
                            "units": {},
                        }
                    }
                },
                SecCompanyFactsPayloadError,
            ),
            (
                {
                    "": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    {"val": 100.0, "accn": "0000320193-24-000010", "form": "10-K", "filed": "2024-11-01"}
                                ]
                            }
                        }
                    }
                },
                SecCompanyFactsPayloadError,
            ),
            (
                {
                    "USD": [
                        {"val": {"bad": "value"}, "accn": "0000320193-24-000010", "form": "10-K", "filed": "2024-11-01"}
                    ]
                },
                SecUnsupportedFactValueError,
            ),
        ]

        for units, error_type in cases:
            with self.subTest(units=units):
                def handler(request: httpx.Request) -> httpx.Response:
                    return httpx.Response(
                        200,
                        json={
                            "cik": 320193,
                            "entityName": "Apple Inc.",
                            "facts": {
                                "us-gaap": {
                                    "Revenues": {
                                        "units": units,
                                    }
                                }
                            },
                        },
                    )

                client = self._build_client(handler)

                with self.assertRaises(error_type):
                    client.get_company_facts(320193)

    def test_malformed_taxonomy_and_concept_raise_validation_error(self) -> None:
        payloads = [
            {"facts": {"us-gaap": {"": {"units": {"USD": [{"val": 100.0, "accn": "0000320193-24-000010", "form": "10-K", "filed": "2024-11-01"}]}}}}},
            {"facts": {"us-gaap": {"Revenues": []}}},
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                def handler(request: httpx.Request) -> httpx.Response:
                    response_payload = {"cik": 320193, "entityName": "Apple Inc."}
                    response_payload.update(payload)
                    return httpx.Response(200, json=response_payload)

                client = self._build_client(handler)

                with self.assertRaises(SecCompanyFactsPayloadError):
                    client.get_company_facts(320193)

    def test_malformed_json_raises_validation_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="{not-json")

        client = self._build_client(handler)

        with self.assertRaises(SecResponseValidationError):
            client.get_company_tickers()
