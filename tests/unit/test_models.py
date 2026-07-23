"""Canonical model unit tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.models.evidence import (
    EvidenceConflict,
    EvidenceCoverage,
    EvidenceRecord,
    RejectedEvidenceRecord,
)
from app.models.execution import (
    ArtifactRecord,
    ExecutionContext,
    ExecutionResult,
    NodeExecutionRecord,
    RuntimeConfig,
    WorkflowError,
    WorkflowWarning,
)
from app.models.providers import FinancialMetric, MarketFinding, NewsEvent, RAGResult
from app.models.report import ReportSection, ReportValidationResult
from app.models.request import ResearchRequest
from app.models.research import ResearchPlan, ResearchTask
from app.models.sources import SourceRecord


class CanonicalModelTests(unittest.TestCase):
    """Validation and serialization checks for canonical models."""

    def test_canonical_models_are_valid_and_serializable(self) -> None:
        models = [
            ExecutionContext(execution_id="exec_1", created_at="2026-07-23T00:00:00Z"),
            RuntimeConfig(),
            ResearchRequest(company_name="Apple Inc.", ticker="AAPL"),
            ResolvedCompany(company_name="Apple Inc.", ticker="AAPL"),
            ResearchTask(task_id="task_1", title="Collect SEC filings"),
            ResearchPlan(company_name="Apple Inc.", tasks=[ResearchTask(task_id="task_1", title="Collect SEC filings")]),
            DocumentRecord(
                document_id="doc_1",
                company_name="Apple Inc.",
                source_id="source_1",
                document_type="sec_filing",
            ),
            SourceRecord(
                source_id="source_1",
                company_name="Apple Inc.",
                provider_name="SEC EDGAR",
                authority_level="primary",
                acquired_at="2026-07-23T00:00:00Z",
            ),
            EvidenceRecord(
                evidence_id="evidence_1",
                company_name="Apple Inc.",
                source_id="source_1",
                claim="Apple reported revenue growth.",
                evidence_classification="regulatory",
            ),
            RejectedEvidenceRecord(
                rejected_evidence_id="rejected_1",
                company_name="Apple Inc.",
                source_id="source_1",
                rejected_text="Unsupported claim.",
                rejection_reason="unsupported",
            ),
            FinancialMetric(
                metric_id="metric_1",
                company_name="Apple Inc.",
                metric_name="Revenue",
                value=100.0,
                period="2025-Q4",
                source_id="source_1",
            ),
            NewsEvent(
                event_id="news_1",
                company_name="Apple Inc.",
                title="Apple announces results",
                published_at="2026-07-23",
                source_id="source_1",
            ),
            MarketFinding(
                finding_id="finding_1",
                company_name="Apple Inc.",
                title="Market context",
                source_id="source_1",
            ),
            RAGResult(
                result_id="rag_1",
                company_name="Apple Inc.",
                document_id="doc_1",
                chunk_id="chunk_1",
                source_id="source_1",
                text="Relevant excerpt.",
            ),
            EvidenceConflict(
                conflict_id="conflict_1",
                company_name="Apple Inc.",
                source_ids=["source_1", "source_2"],
                description="Conflicting revenue figures.",
            ),
            EvidenceCoverage(
                coverage_status="sufficient",
                covered_sections=["financial performance"],
                missing_sections=[],
                notes=["All required sections are covered."],
            ),
            ReportSection(
                section_id="section_1",
                title="Executive Summary",
                order=1,
                content="Summary content.",
            ),
            ReportValidationResult(status="valid"),
            WorkflowWarning(code="warning_1", message="Optional source unavailable."),
            WorkflowError(code="error_1", message="Required source failed."),
            NodeExecutionRecord(node_name="initialize_request", status="completed"),
            ArtifactRecord(artifact_id="artifact_1", artifact_type="markdown", path="outputs/report.md"),
            ExecutionResult(execution_id="exec_1", status="completed"),
        ]

        for model in models:
            with self.subTest(model=type(model).__name__):
                payload = asdict(model)
                json.dumps(payload)

    def test_invalid_inputs_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            ResearchRequest()

        with self.assertRaises(ValueError):
            SourceRecord(
                source_id="source_1",
                company_name="",
                provider_name="SEC EDGAR",
                authority_level="primary",
                acquired_at="2026-07-23T00:00:00Z",
            )

        with self.assertRaises(ValueError):
            ReportValidationResult(status="invalid_status")  # type: ignore[arg-type]

