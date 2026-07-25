"""Unit tests for source registration helpers."""

from __future__ import annotations

import unittest

from app.models.sources import SourceRecord
from app.services.source_registration_service import register_sources


class SourceRegistrationServiceTests(unittest.TestCase):
    """Offline tests for deterministic source registration preparation."""

    def setUp(self) -> None:
        self.first_source = SourceRecord(
            source_id="source_1",
            company_name="Apple Inc.",
            provider_name="SEC EDGAR",
            authority_level="primary",
            acquired_at="2026-07-23T00:00:00Z",
            raw_reference="old-reference",
        )
        self.replacement_source = SourceRecord(
            source_id="source_1",
            company_name="Apple Inc.",
            provider_name="SEC EDGAR",
            authority_level="primary",
            acquired_at="2026-07-24T00:00:00Z",
            raw_reference="new-reference",
        )
        self.other_source = SourceRecord(
            source_id="source_2",
            company_name="Apple Inc.",
            provider_name="SEC EDGAR",
            authority_level="primary",
            acquired_at="2026-07-23T00:00:00Z",
        )

    def test_register_sources_replaces_duplicate_identifiers_deterministically(self) -> None:
        registered = register_sources([self.first_source, self.other_source, self.replacement_source])

        self.assertEqual(registered, (self.replacement_source, self.other_source))

    def test_register_sources_is_stable_on_replay(self) -> None:
        first = register_sources([self.first_source, self.other_source, self.replacement_source])
        second = register_sources([self.first_source, self.other_source, self.replacement_source])

        self.assertEqual(first, second)

    def test_register_sources_handles_empty_input(self) -> None:
        self.assertEqual(register_sources([]), ())
