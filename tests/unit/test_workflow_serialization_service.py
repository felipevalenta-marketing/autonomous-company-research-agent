"""Unit tests for the workflow serialization contract."""

from __future__ import annotations

import json
import re
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_output_service import WorkflowOutput
from app.services.workflow_serialization_service import (
    WorkflowSerializationConsistencyError,
    WorkflowSerializationInputError,
    serialize_workflow_output,
)


class WorkflowSerializationServiceTests(unittest.TestCase):
    """Offline tests for workflow serialization."""

    def _build_company(self) -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def _build_evidence_record(self, result_id: str = "result-1") -> RAGEvidenceRecord:
        return RAGEvidenceRecord(
            result_id=result_id,
            query="Assess Apple",
            company_name="Apple Inc.",
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-1",
            text="Relevant retrieved passage.",
            similarity_score=0.92,
            retrieval_scope="company:cik:0000320193",
            source_url="https://example.com/doc",
        )

    def _build_bundle(self, query: str = "Assess Apple", evidence: tuple[RAGEvidenceRecord, ...] = ()) -> EvidenceBundle:
        return EvidenceBundle(
            query=query,
            evidence_count=len(evidence),
            evidence=evidence,
            source_count=len({item.source_id for item in evidence if item.source_id.strip()}),
            document_count=len({item.document_id for item in evidence if item.document_id.strip()}),
        )

    def _build_output(self) -> WorkflowOutput:
        return WorkflowOutput(
            research_query="Assess Apple",
            resolved_company=self._build_company(),
            evidence_bundle=self._build_bundle(evidence=(self._build_evidence_record(),)),
        )

    def test_successful_serialization_returns_json_compatible_payload(self) -> None:
        workflow_output = self._build_output()

        payload = serialize_workflow_output(workflow_output)
        expected = asdict(workflow_output)
        expected["evidence_bundle"]["evidence"] = list(expected["evidence_bundle"]["evidence"])

        self.assertEqual(tuple(payload.keys()), ("research_query", "resolved_company", "evidence_bundle"))
        self.assertEqual(payload, expected)
        self.assertEqual(tuple(payload["resolved_company"].keys()), ("company_name", "ticker", "cik", "exchange", "country", "security_type", "company_id", "website_url"))
        self.assertEqual(tuple(payload["evidence_bundle"].keys()), ("query", "evidence_count", "evidence", "source_count", "document_count"))
        self.assertEqual(tuple(payload["evidence_bundle"]["evidence"][0].keys()), ("result_id", "query", "company_name", "source_id", "document_id", "chunk_id", "text", "similarity_score", "retrieval_scope", "source_url"))
        json.dumps(payload)

    def test_nested_evidence_serialization_preserves_values(self) -> None:
        workflow_output = self._build_output()

        payload = serialize_workflow_output(workflow_output)

        self.assertEqual(payload["research_query"], workflow_output.research_query)
        self.assertEqual(payload["resolved_company"]["company_name"], workflow_output.resolved_company.company_name)
        self.assertEqual(payload["evidence_bundle"]["query"], workflow_output.evidence_bundle.query)
        self.assertEqual(payload["evidence_bundle"]["evidence"][0]["result_id"], workflow_output.evidence_bundle.evidence[0].result_id)
        self.assertEqual(payload["evidence_bundle"]["evidence"][0]["text"], workflow_output.evidence_bundle.evidence[0].text)

    def test_invalid_workflow_output_rejected(self) -> None:
        malformed = object.__new__(WorkflowOutput)
        object.__setattr__(malformed, "research_query", " ")
        object.__setattr__(malformed, "resolved_company", self._build_company())
        object.__setattr__(malformed, "evidence_bundle", self._build_bundle(evidence=(self._build_evidence_record(),)))

        with self.assertRaises(WorkflowSerializationConsistencyError):
            serialize_workflow_output(malformed)

    def test_wrong_input_type_rejected(self) -> None:
        with self.assertRaises(WorkflowSerializationInputError):
            serialize_workflow_output(object())  # type: ignore[arg-type]

    def test_invalid_evidence_rejected(self) -> None:
        workflow_output = self._build_output()
        malformed_bundle = object.__new__(EvidenceBundle)
        object.__setattr__(malformed_bundle, "query", workflow_output.evidence_bundle.query)
        object.__setattr__(malformed_bundle, "evidence_count", 1)
        object.__setattr__(malformed_bundle, "evidence", (object(),))
        object.__setattr__(malformed_bundle, "source_count", 0)
        object.__setattr__(malformed_bundle, "document_count", 0)
        object.__setattr__(workflow_output, "evidence_bundle", malformed_bundle)

        with self.assertRaises(WorkflowSerializationConsistencyError):
            serialize_workflow_output(workflow_output)

    def test_invalid_company_rejected(self) -> None:
        workflow_output = self._build_output()
        malformed_company = object.__new__(ResolvedCompany)
        object.__setattr__(malformed_company, "company_name", "Apple Inc.")
        object.__setattr__(malformed_company, "ticker", 123)
        object.__setattr__(malformed_company, "cik", "0000320193")
        object.__setattr__(malformed_company, "exchange", None)
        object.__setattr__(malformed_company, "country", None)
        object.__setattr__(malformed_company, "security_type", None)
        object.__setattr__(malformed_company, "company_id", None)
        object.__setattr__(malformed_company, "website_url", None)
        object.__setattr__(workflow_output, "resolved_company", malformed_company)

        with self.assertRaises(WorkflowSerializationConsistencyError):
            serialize_workflow_output(workflow_output)

    def test_failed_workflow_like_input_rejected(self) -> None:
        workflow_output = self._build_output()
        object.__setattr__(workflow_output, "research_query", "")

        with self.assertRaises(WorkflowSerializationConsistencyError):
            serialize_workflow_output(workflow_output)

    def test_deterministic_replay(self) -> None:
        workflow_output = self._build_output()

        first = serialize_workflow_output(workflow_output)
        second = serialize_workflow_output(workflow_output)

        self.assertEqual(first, second)

    def test_input_remains_unchanged(self) -> None:
        workflow_output = self._build_output()
        snapshot = asdict(workflow_output)

        serialize_workflow_output(workflow_output)

        self.assertEqual(asdict(workflow_output), snapshot)

        with self.assertRaises(FrozenInstanceError):
            workflow_output.research_query = "changed"  # type: ignore[misc]

    def test_import_isolation(self) -> None:
        source = Path("app/services/workflow_serialization_service.py").read_text(encoding="utf-8").lower()
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(stripped.startswith("import openai"))
            self.assertFalse(stripped.startswith("from openai"))
            self.assertFalse(stripped.startswith("import langchain"))
            self.assertFalse(stripped.startswith("from langchain"))
            self.assertFalse(stripped.startswith("import pinecone"))
            self.assertFalse(stripped.startswith("from pinecone"))
            self.assertFalse(stripped.startswith("import fastapi"))
            self.assertFalse(stripped.startswith("from fastapi"))
            self.assertFalse(stripped.startswith("import flask"))
            self.assertFalse(stripped.startswith("from flask"))
        for forbidden in (
            "n8n",
            "report generation",
            "markdown",
            "pdf",
            "exporter",
            "persistence",
            "checkpoint",
            "uuid",
            "random",
            "datetime.now",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIsNone(re.search(r"\bui\b", source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
