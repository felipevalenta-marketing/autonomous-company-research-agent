"""Unit tests for SEC DTO validation and serialization."""

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
    SecTickerRecord,
)


class SecTickerRecordTests(unittest.TestCase):
    """Validation and serialization checks for SEC ticker DTOs."""

    def test_valid_construction_is_serializable(self) -> None:
        record = SecTickerRecord(cik=320193, ticker="AAPL", title="Apple Inc.")

        self.assertEqual(record.cik, 320193)
        self.assertEqual(record.ticker, "AAPL")
        self.assertEqual(record.title, "Apple Inc.")
        json.dumps(asdict(record))

    def test_blank_ticker_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            SecTickerRecord(cik=320193, ticker=" ", title="Apple Inc.")

    def test_blank_company_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            SecTickerRecord(cik=320193, ticker="AAPL", title=" ")

    def test_non_positive_cik_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            SecTickerRecord(cik=0, ticker="AAPL", title="Apple Inc.")

        with self.assertRaises(ValueError):
            SecTickerRecord(cik=-1, ticker="AAPL", title="Apple Inc.")

    def test_submission_and_fact_dtos_are_serializable(self) -> None:
        filing = SecRecentFilingRecord(
            accession_number="0000320193-24-000010",
            filing_date="2024-11-01",
            form="10-K",
            primary_document="aapl-20240928x10k.htm",
            report_date="2024-09-30",
            acceptance_datetime="2024-11-01T16:00:00Z",
        )
        submissions = SecSubmissionsResponse(
            cik=320193,
            entity_name="Apple Inc.",
            recent_filings=(filing,),
        )
        observation = SecFactObservation(
            value=123.0,
            unit="USD",
            accession_number="0000320193-24-000010",
            form="10-K",
            filed_date="2024-11-01",
            fiscal_year=2024,
            fiscal_period="FY",
            start_date="2023-10-01",
            end_date="2024-09-30",
        )
        concept = SecFactConcept(
            taxonomy="us-gaap",
            concept="Revenues",
            observations=(observation,),
        )
        facts = SecCompanyFactsResponse(cik=320193, entity_name="Apple Inc.", concepts=(concept,))

        json.dumps(asdict(submissions))
        json.dumps(asdict(facts))

    def test_text_fact_observation_is_supported(self) -> None:
        observation = SecFactObservation(
            value="N/A",
            unit="shares",
            accession_number="0000320193-24-000010",
            form="10-K",
            filed_date="2024-11-01",
        )

        self.assertEqual(observation.value, "N/A")

    def test_empty_fact_concept_observations_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            SecFactConcept(taxonomy="us-gaap", concept="Revenues", observations=())

    def test_invalid_recent_filing_fields_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            SecRecentFilingRecord(
                accession_number=" ",
                filing_date="2024-11-01",
                form="10-K",
                primary_document="aapl-20240928x10k.htm",
            )

        with self.assertRaises(ValueError):
            SecFactObservation(
                value=1,
                unit="USD",
                accession_number="0000320193-24-000010",
                form="10-K",
                filed_date="2024-11-01",
                fiscal_year=-1,
            )
