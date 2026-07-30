"""Unit tests for the workflow output contract."""

from __future__ import annotations

import json
import re
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_output_service import (
    WorkflowOutput,
    WorkflowOutputConsistencyError,
    WorkflowOutputInputError,
    build_workflow_output,
)


class WorkflowOutputServiceTests(unittest.TestCase):
    """Offline tests for workflow output packaging."""

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

    def _build_completed_state(self, *, evidence_bundle: EvidenceBundle | None = None) -> dict[str, object]:
        return {
            "research_query": "Assess Apple",
            "resolved_company": self._build_company(),
            "evidence_bundle": evidence_bundle if evidence_bundle is not None else self._build_bundle(
                evidence=(self._build_evidence_record(),),
            ),
            "workflow_status": "completed",
            "current_stage": "completed",
        }

    def test_successful_completed_workflow_returns_immutable_output(self) -> None:
        state = self._build_completed_state()

        output = build_workflow_output(state)

        self.assertIsInstance(output, WorkflowOutput)
        self.assertEqual(output.research_query, state["research_query"])
        self.assertEqual(output.resolved_company, state["resolved_company"])
        self.assertEqual(output.evidence_bundle, state["evidence_bundle"])
        self.assertEqual(tuple(asdict(output).keys()), ("research_query", "resolved_company", "evidence_bundle"))
        json.dumps(asdict(output))

        with self.assertRaises(FrozenInstanceError):
            output.research_query = "changed"  # type: ignore[misc]

    def test_failed_workflow_rejected(self) -> None:
        state = self._build_completed_state()
        state["workflow_status"] = "failed"
        state["current_stage"] = "failed"

        with self.assertRaises(WorkflowOutputInputError):
            build_workflow_output(state)

    def test_missing_evidence_rejected(self) -> None:
        state = self._build_completed_state()
        state.pop("evidence_bundle")

        with self.assertRaises(WorkflowOutputConsistencyError):
            build_workflow_output(state)

    def test_missing_company_rejected(self) -> None:
        state = self._build_completed_state()
        state.pop("resolved_company")

        with self.assertRaises(WorkflowOutputConsistencyError):
            build_workflow_output(state)

    def test_malformed_workflow_state_rejected(self) -> None:
        malformed = self._build_completed_state()
        malformed["evidence_bundle"] = self._build_bundle(query="Different query", evidence=(self._build_evidence_record(),))

        with self.assertRaises(WorkflowOutputConsistencyError):
            build_workflow_output(malformed)

    def test_deterministic_replay(self) -> None:
        state = self._build_completed_state()

        first = build_workflow_output(state)
        second = build_workflow_output(state)

        self.assertEqual(first, second)

    def test_input_remains_unchanged(self) -> None:
        state = self._build_completed_state()
        snapshot = dict(state)

        build_workflow_output(state)

        self.assertEqual(state, snapshot)

    def test_import_isolation(self) -> None:
        source = Path("app/services/workflow_output_service.py").read_text(encoding="utf-8").lower()
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(stripped.startswith("import openai"))
            self.assertFalse(stripped.startswith("from openai"))
            self.assertFalse(stripped.startswith("import langchain"))
            self.assertFalse(stripped.startswith("from langchain"))
            self.assertFalse(stripped.startswith("import pinecone"))
            self.assertFalse(stripped.startswith("from pinecone"))
        for forbidden in (
            "report",
            "prompt",
            "exporter",
            "n8n",
            "persistence",
            "checkpoint",
            "api",
            "uuid",
            "random",
            "datetime.now",
            "llm",
            "markdown",
            "pdf",
            "citation",
            "tokens",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIsNone(re.search(r"\bui\b", source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
