"""Unit tests for the workflow integration boundary."""

from __future__ import annotations

import json
import re
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_integration_service import (
    WorkflowIntegrationConsistencyError,
    WorkflowIntegrationInputError,
    run_completed_workflow,
)
from app.services.workflow_output_service import WorkflowOutput
from app.services.workflow_serialization_service import WorkflowSerializationConsistencyError


class FakeSerializationDependency:
    def __init__(self, response: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[WorkflowOutput] = []

    def __call__(self, workflow_output: WorkflowOutput) -> dict[str, object]:
        self.calls.append(workflow_output)
        if self.exc is not None:
            raise self.exc
        if self.response is None:
            raise AssertionError("fake serialization dependency was not configured.")
        return self.response


class WorkflowIntegrationServiceTests(unittest.TestCase):
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

    def test_valid_workflow_output_delegates_once_and_returns_exact_dict(self) -> None:
        workflow_output = self._build_output()
        expected = {
            "research_query": workflow_output.research_query,
            "resolved_company": asdict(workflow_output.resolved_company),
            "evidence_bundle": asdict(workflow_output.evidence_bundle),
        }
        dependency = FakeSerializationDependency(response=expected)

        payload = run_completed_workflow(workflow_output, serialization_dependency=dependency)

        self.assertEqual(dependency.calls, [workflow_output])
        self.assertIs(payload, expected)
        self.assertEqual(payload, expected)
        json.dumps(payload)

    def test_invalid_input_type_rejected(self) -> None:
        with self.assertRaises(WorkflowIntegrationInputError):
            run_completed_workflow(object())  # type: ignore[arg-type]

    def test_invalid_serialization_dependency_rejected(self) -> None:
        workflow_output = self._build_output()

        with self.assertRaises(WorkflowIntegrationInputError):
            run_completed_workflow(workflow_output, serialization_dependency=None)  # type: ignore[arg-type]

    def test_input_object_remains_unchanged(self) -> None:
        workflow_output = self._build_output()
        snapshot = asdict(workflow_output)
        dependency = FakeSerializationDependency(
            response={
                "research_query": workflow_output.research_query,
                "resolved_company": asdict(workflow_output.resolved_company),
                "evidence_bundle": asdict(workflow_output.evidence_bundle),
            }
        )

        run_completed_workflow(workflow_output, serialization_dependency=dependency)

        self.assertEqual(asdict(workflow_output), snapshot)
        with self.assertRaises(FrozenInstanceError):
            workflow_output.research_query = "changed"  # type: ignore[misc]

    def test_typed_serialization_error_propagates_unchanged(self) -> None:
        workflow_output = self._build_output()
        dependency = FakeSerializationDependency(exc=WorkflowSerializationConsistencyError("serialization failed"))

        with self.assertRaises(WorkflowSerializationConsistencyError):
            run_completed_workflow(workflow_output, serialization_dependency=dependency)

    def test_non_dictionary_dependency_result_rejected(self) -> None:
        workflow_output = self._build_output()
        dependency = FakeSerializationDependency(response=[("research_query", "Assess Apple")])  # type: ignore[list-item]

        with self.assertRaises(WorkflowIntegrationConsistencyError):
            run_completed_workflow(workflow_output, serialization_dependency=dependency)

    def test_deterministic_replay(self) -> None:
        workflow_output = self._build_output()
        dependency_one = FakeSerializationDependency(
            response={
                "research_query": workflow_output.research_query,
                "resolved_company": asdict(workflow_output.resolved_company),
                "evidence_bundle": asdict(workflow_output.evidence_bundle),
            }
        )
        dependency_two = FakeSerializationDependency(
            response={
                "research_query": workflow_output.research_query,
                "resolved_company": asdict(workflow_output.resolved_company),
                "evidence_bundle": asdict(workflow_output.evidence_bundle),
            }
        )

        first = run_completed_workflow(workflow_output, serialization_dependency=dependency_one)
        second = run_completed_workflow(workflow_output, serialization_dependency=dependency_two)

        self.assertEqual(first, second)
        self.assertEqual(dependency_one.calls, [workflow_output])
        self.assertEqual(dependency_two.calls, [workflow_output])

    def test_import_isolation(self) -> None:
        source = Path("app/services/workflow_integration_service.py").read_text(encoding="utf-8").lower()
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
            "webhook",
            "n8n",
            "report",
            "prompt",
            "markdown",
            "pdf",
            "exporter",
            "persistence",
            "os.environ",
            "os.getenv",
            "datetime.now",
            "uuid",
            "random",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIsNone(re.search(r"\bui\b", source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
