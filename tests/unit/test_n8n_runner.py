"""Unit tests for the executable workflow adapter."""

from __future__ import annotations

import importlib
import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from app.models.company import ResolvedCompany
from app.settings import Settings
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_integration_service import WorkflowIntegrationConsistencyError
from app.services.workflow_output_service import WorkflowOutput, WorkflowOutputError


class RecordingWorkflow:
    def __init__(self, result: object | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def invoke(self, state: dict[str, object]) -> object:
        self.calls.append(dict(state))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("workflow result was not configured.")
        return self.result


class RecordingBuilder:
    def __init__(self, result: WorkflowOutput | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[object] = []

    def __call__(self, state: object) -> WorkflowOutput:
        self.calls.append(state)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("workflow output was not configured.")
        return self.result


class RecordingIntegration:
    def __init__(self, result: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[WorkflowOutput] = []

    def __call__(self, workflow_output: WorkflowOutput) -> dict[str, object]:
        self.calls.append(workflow_output)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("integration result was not configured.")
        return self.result


class N8nRunnerTests(unittest.TestCase):
    def _build_company(self) -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def _build_evidence_record(self) -> RAGEvidenceRecord:
        return RAGEvidenceRecord(
            result_id="result-1",
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

    def _build_workflow_output(self) -> WorkflowOutput:
        evidence = self._build_evidence_record()
        bundle = EvidenceBundle(
            query="Assess Apple",
            evidence_count=1,
            evidence=(evidence,),
            source_count=1,
            document_count=1,
        )
        return WorkflowOutput(
            research_query="Assess Apple",
            resolved_company=self._build_company(),
            evidence_bundle=bundle,
        )

    def _build_payload(self) -> dict[str, object]:
        workflow_output = self._build_workflow_output()
        return {
            "research_query": workflow_output.research_query,
            "resolved_company": asdict(workflow_output.resolved_company),
            "evidence_bundle": {
                "query": workflow_output.evidence_bundle.query,
                "evidence_count": workflow_output.evidence_bundle.evidence_count,
                "evidence": [asdict(item) for item in workflow_output.evidence_bundle.evidence],
                "source_count": workflow_output.evidence_bundle.source_count,
                "document_count": workflow_output.evidence_bundle.document_count,
            },
        }

    def _build_settings(self) -> Settings:
        return Settings(
            openai_api_key="demo",
            openai_base_url="https://api.openai.com/v1",
            openai_embedding_model="text-embedding-3-small",
            pinecone_api_key="demo",
            pinecone_index_name="index",
            pinecone_index_host="https://example.com",
            pinecone_namespace_prefix="company",
            pinecone_vector_dimension="3",
            pinecone_api_version=None,
            pinecone_max_upsert_batch_size="10",
            pinecone_max_query_top_k="5",
            tavily_api_key=None,
            news_api_key=None,
            alpha_vantage_api_key=None,
            sec_user_agent="Example App (dev@example.com)",
        )

    def _build_dependencies_factory(
        self,
        *,
        workflow: RecordingWorkflow,
        builder: RecordingBuilder,
        integration: RecordingIntegration,
    ):
        def factory(settings: Settings, args: object) -> SimpleNamespace:
            self.factory_calls.append((settings, args))
            return SimpleNamespace(
                workflow=workflow,
                build_workflow_output=builder,
                run_completed_workflow=integration,
            )

        return factory

    def setUp(self) -> None:
        self.runner_module = importlib.import_module("app.n8n_runner")
        self.factory_calls: list[tuple[Settings, object]] = []

    def test_successful_execution_writes_single_json_object(self) -> None:
        workflow_output = self._build_workflow_output()
        payload = self._build_payload()
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=workflow_output)
        integration = RecordingIntegration(result=payload)
        settings = self._build_settings()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "Assess Apple"],
            settings_loader=lambda: settings,
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(json.loads(stdout.getvalue()), payload)
        self.assertEqual(workflow.calls, [{"research_query": "Assess Apple", "company_input": "Apple Inc."}])
        self.assertEqual(len(builder.calls), 1)
        self.assertEqual(len(integration.calls), 1)
        self.assertIs(integration.calls[0], workflow_output)

    def test_invalid_company_rejected_before_execution(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()
        settings_called = {"count": 0}

        def settings_loader() -> Settings:
            settings_called["count"] += 1
            raise AssertionError("settings should not be loaded for invalid CLI input.")

        exit_code = self.runner_module.main(
            ["--company", "", "--query", "Assess Apple"],
            settings_loader=settings_loader,
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--company must be a non-blank string.", stderr.getvalue())
        self.assertEqual(settings_called["count"], 0)
        self.assertEqual(workflow.calls, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_missing_company_rejected_before_execution(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--query", "Assess Apple"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--company must be a non-blank string.", stderr.getvalue())
        self.assertEqual(workflow.calls, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_blank_query_rejected_before_execution(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "   "],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--query must be a non-blank string.", stderr.getvalue())
        self.assertEqual(workflow.calls, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_missing_query_rejected_before_execution(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc."],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--query must be a non-blank string.", stderr.getvalue())
        self.assertEqual(workflow.calls, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_invalid_numeric_arguments_rejected(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "Assess Apple", "--top-k", "0"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--top-k must be a positive integer when provided.", stderr.getvalue())
        self.assertEqual(workflow.calls, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_workflow_failure_returns_nonzero_and_no_stdout(self) -> None:
        workflow = RecordingWorkflow(error=RuntimeError("workflow failed"))
        builder = RecordingBuilder(result=self._build_workflow_output())
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "Assess Apple"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error: workflow execution failed.", stderr.getvalue())
        self.assertEqual(builder.calls, [])
        self.assertEqual(integration.calls, [])

    def test_workflow_output_failure_returns_nonzero(self) -> None:
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(error=WorkflowOutputError("output failed"))
        integration = RecordingIntegration(result=self._build_payload())
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "Assess Apple"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error: completed workflow output could not be built.", stderr.getvalue())
        self.assertEqual(len(workflow.calls), 1)
        self.assertEqual(integration.calls, [])

    def test_integration_failure_returns_nonzero(self) -> None:
        workflow_output = self._build_workflow_output()
        workflow = RecordingWorkflow(result={"final": "state"})
        builder = RecordingBuilder(result=workflow_output)
        integration = RecordingIntegration(error=WorkflowIntegrationConsistencyError("bad payload"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--query", "Assess Apple"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                workflow=workflow,
                builder=builder,
                integration=integration,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error: workflow integration failed.", stderr.getvalue())
        self.assertEqual(len(builder.calls), 1)
        self.assertEqual(len(integration.calls), 1)

    def test_import_isolation(self) -> None:
        snapshot = dict(os.environ)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            module = importlib.reload(importlib.import_module("app.n8n_runner"))

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(dict(os.environ), snapshot)
        source = Path(module.__file__).read_text(encoding="utf-8").lower()
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
            self.assertFalse(stripped.startswith("import django"))
            self.assertFalse(stripped.startswith("from django"))
        for pattern in (
            r"\bwebhook\b",
            r"\bn8n\b",
            r"\breact\b",
            r"\breport\b",
            r"\bprompt\b",
            r"\bmarkdown\b",
            r"\bpdf\b",
            r"\bexporter\b",
            r"\buuid\b",
            r"datetime\.now",
            r"\brandom\b",
        ):
            self.assertIsNone(re.search(pattern, source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
