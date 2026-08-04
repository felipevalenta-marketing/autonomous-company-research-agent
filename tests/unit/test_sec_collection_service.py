"""Unit tests for SEC collection orchestration."""

from __future__ import annotations

import inspect
import sys
import unittest

from app.clients.sec_dtos import SecCompanyFactsResponse, SecFactConcept, SecFactObservation, SecRecentFilingRecord, SecSubmissionsResponse
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.services.sec_collection_service import SecCollectionInputError, collect_financial_data, collect_sec_documents


class FakeSecClient:
    """In-memory SEC client for offline orchestration tests."""

    def __init__(self, submissions: SecSubmissionsResponse, facts: SecCompanyFactsResponse) -> None:
        self.submissions = submissions
        self.facts = facts
        self.submission_calls: list[str | int] = []
        self.fact_calls: list[str | int] = []

    def get_company_submissions(self, cik: int | str) -> SecSubmissionsResponse:
        self.submission_calls.append(cik)
        return self.submissions

    def get_company_facts(self, cik: int | str) -> SecCompanyFactsResponse:
        self.fact_calls.append(cik)
        return self.facts


class SecCollectionServiceTests(unittest.TestCase):
    """Offline tests for SEC collection orchestration."""

    def setUp(self) -> None:
        self.resolved_company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")
        self.runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")
        self.submissions = SecSubmissionsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            recent_filings=(
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000010",
                    filing_date="2024-11-01",
                    form="10-K",
                    primary_document="aapl-20240928x10k.htm",
                    report_date="2024-09-30",
                    acceptance_datetime="2024-11-01T16:00:00Z",
                ),
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000011",
                    filing_date="2024-08-01",
                    form="4",
                    primary_document="aapl.htm",
                ),
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000010",
                    filing_date="2024-11-01",
                    form="10-K",
                    primary_document="aapl-20240928x10k.htm",
                    report_date="2024-09-30",
                    acceptance_datetime="2024-11-01T16:00:00Z",
                ),
            ),
        )
        self.facts = SecCompanyFactsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            concepts=(
                SecFactConcept(
                    taxonomy="us-gaap",
                    concept="Revenues",
                    observations=(
                        SecFactObservation(
                            value=100.0,
                            unit="USD",
                            accession_number="0000320193-24-000010",
                            form="10-K",
                            filed_date="2024-11-01",
                            fiscal_year=2024,
                            fiscal_period="FY",
                            start_date="2023-10-01",
                            end_date="2024-09-30",
                        ),
                    ),
                ),
            ),
        )

    def _langgraph_module_snapshot(self) -> dict[str, int]:
        return {
            name: id(module)
            for name, module in sys.modules.items()
            if name == "langgraph" or name.startswith("langgraph.")
        }

    def test_collect_sec_documents_returns_documents_and_sources(self) -> None:
        client = FakeSecClient(self.submissions, self.facts)

        documents, sources = collect_sec_documents(self.resolved_company, client, self.runtime_config)

        self.assertEqual(client.submission_calls, ["0000320193"])
        self.assertEqual(client.fact_calls, [])
        self.assertIsInstance(documents, tuple)
        self.assertIsInstance(sources, tuple)
        self.assertEqual(len(documents), 1)
        self.assertEqual(len(sources), 1)
        self.assertEqual(documents[0].filing_type, "10-K")
        self.assertEqual(documents[0].source_id, sources[0].source_id)
        self.assertEqual(documents[0].source_url, sources[0].source_url)
        self.assertEqual(documents[0].document_id, sources[0].document_id)
        self.assertTrue(documents[0].source_url.startswith("https://www.sec.gov/Archives/edgar/data/320193/"))

    def test_collect_sec_documents_rejects_missing_cik(self) -> None:
        client = FakeSecClient(self.submissions, self.facts)
        company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL")

        with self.assertRaises(SecCollectionInputError):
            collect_sec_documents(company, client, self.runtime_config)

    def test_collect_financial_data_returns_metrics_only_when_explicitly_invoked(self) -> None:
        client = FakeSecClient(self.submissions, self.facts)

        metrics = collect_financial_data(self.resolved_company, client, self.runtime_config)

        self.assertEqual(client.submission_calls, [])
        self.assertEqual(client.fact_calls, ["0000320193"])
        self.assertIsInstance(metrics, tuple)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].metric_name, "Revenue")
        self.assertEqual(metrics[0].value, 100.0)
        self.assertEqual(metrics[0].period, "2024-FY")

    def test_collect_financial_data_is_deterministic(self) -> None:
        client = FakeSecClient(self.submissions, self.facts)

        first = collect_financial_data(self.resolved_company, client, self.runtime_config)
        second = collect_financial_data(self.resolved_company, client, self.runtime_config)

        self.assertEqual(first, second)

    def test_service_does_not_require_shared_state_or_langgraph(self) -> None:
        state = {"documents": [], "sources": []}
        client = FakeSecClient(self.submissions, self.facts)
        before_langgraph_modules = self._langgraph_module_snapshot()

        collect_sec_documents(self.resolved_company, client, self.runtime_config)
        collect_financial_data(self.resolved_company, client, self.runtime_config)

        self.assertEqual(state, {"documents": [], "sources": []})
        self.assertEqual(before_langgraph_modules, self._langgraph_module_snapshot())

    def test_service_signatures_do_not_accept_state_inputs(self) -> None:
        self.assertNotIn("state", inspect.signature(collect_sec_documents).parameters)
        self.assertNotIn("state", inspect.signature(collect_financial_data).parameters)
