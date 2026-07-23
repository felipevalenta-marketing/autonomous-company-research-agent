"""Unit tests for SEC normalization services."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.sec_dtos import (
    SecCompanyFactsResponse,
    SecFactConcept,
    SecFactObservation,
    SecRecentFilingRecord,
    SecSubmissionsResponse,
)
from app.models.company import ResolvedCompany
from app.services.sec_normalization_service import (
    normalize_sec_company_facts,
    normalize_sec_submissions,
)


class SecNormalizationTests(unittest.TestCase):
    """Offline tests for SEC-to-canonical normalization."""

    def setUp(self) -> None:
        self.company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def test_supported_form_produces_documents_and_sources(self) -> None:
        submissions = SecSubmissionsResponse(
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
            ),
        )

        documents, sources = normalize_sec_submissions(self.company, submissions)

        self.assertEqual(len(documents), 1)
        self.assertEqual(len(sources), 1)
        self.assertEqual(documents[0].filing_type, "10-K")
        self.assertEqual(documents[0].source_url, sources[0].source_url)
        self.assertTrue(documents[0].source_url.startswith("https://www.sec.gov/Archives/edgar/data/320193/"))
        json.dumps([asdict(document) for document in documents])
        json.dumps([asdict(source) for source in sources])

    def test_unsupported_form_is_excluded(self) -> None:
        submissions = SecSubmissionsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            recent_filings=(
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000010",
                    filing_date="2024-11-01",
                    form="4",
                    primary_document="aapl.htm",
                ),
            ),
        )

        documents, sources = normalize_sec_submissions(self.company, submissions)

        self.assertEqual(documents, [])
        self.assertEqual(sources, [])

    def test_duplicate_filings_are_removed(self) -> None:
        submissions = SecSubmissionsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            recent_filings=(
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000010",
                    filing_date="2024-11-01",
                    form="10-K",
                    primary_document="aapl-20240928x10k.htm",
                    report_date="2024-09-30",
                ),
                SecRecentFilingRecord(
                    accession_number="0000320193-24-000010",
                    filing_date="2024-11-01",
                    form="10-K",
                    primary_document="aapl-20240928x10k.htm",
                    report_date="2024-09-30",
                ),
            ),
        )

        documents, sources = normalize_sec_submissions(self.company, submissions)

        self.assertEqual(len(documents), 1)
        self.assertEqual(len(sources), 1)

    def test_company_facts_normalize_to_financial_metrics(self) -> None:
        facts = SecCompanyFactsResponse(
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

        metrics = normalize_sec_company_facts(self.company, facts)

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].metric_name, "Revenue")
        self.assertEqual(metrics[0].unit, "USD")
        self.assertEqual(metrics[0].period, "2024-FY")
        json.dumps([asdict(metric) for metric in metrics])

    def test_unsupported_concept_is_ignored(self) -> None:
        facts = SecCompanyFactsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            concepts=(
                SecFactConcept(
                    taxonomy="us-gaap",
                    concept="UnsupportedConcept",
                    observations=(
                        SecFactObservation(
                            value=1,
                            unit="USD",
                            accession_number="0000320193-24-000010",
                            form="10-K",
                            filed_date="2024-11-01",
                        ),
                    ),
                ),
            ),
        )

        metrics = normalize_sec_company_facts(self.company, facts)

        self.assertEqual(metrics, [])

    def test_duplicate_observations_are_removed(self) -> None:
        observation = SecFactObservation(
            value=100.0,
            unit="USD",
            accession_number="0000320193-24-000010",
            form="10-K",
            filed_date="2024-11-01",
            fiscal_year=2024,
            fiscal_period="FY",
            start_date="2023-10-01",
            end_date="2024-09-30",
        )
        facts = SecCompanyFactsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            concepts=(
                SecFactConcept(
                    taxonomy="us-gaap",
                    concept="Revenues",
                    observations=(observation, observation),
                ),
            ),
        )

        metrics = normalize_sec_company_facts(self.company, facts)

        self.assertEqual(len(metrics), 1)

    def test_malformed_observation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SecFactObservation(
                value={"bad": "value"},  # type: ignore[arg-type]
                unit="USD",
                accession_number="0000320193-24-000010",
                form="10-K",
                filed_date="2024-11-01",
            )

    def test_normalization_is_deterministic(self) -> None:
        facts = SecCompanyFactsResponse(
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

        first = normalize_sec_company_facts(self.company, facts)
        second = normalize_sec_company_facts(self.company, facts)

        self.assertEqual(first, second)
        json.dumps(asdict(facts))
