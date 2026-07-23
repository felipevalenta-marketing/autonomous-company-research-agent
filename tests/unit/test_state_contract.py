"""Shared state contract tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict, is_dataclass

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
from app.models.research import ResearchPlan
from app.models.sources import SourceRecord
from app.models.state import (
    STATE_APPEND_FIELDS,
    STATE_COUNTER_FIELDS,
    STATE_REPLACE_FIELDS,
    STATE_UPSERT_FIELDS,
    CompanyResearchState,
)


class SharedStateTests(unittest.TestCase):
    """Tests for the canonical shared state contract."""

    def test_exact_shared_state_fields(self) -> None:
        expected_fields = {
            "state_version",
            "execution_context",
            "request",
            "runtime_config",
            "resolved_company",
            "research_plan",
            "documents",
            "sources",
            "evidence",
            "rejected_evidence",
            "financial_metrics",
            "news_events",
            "market_findings",
            "rag_results",
            "evidence_conflicts",
            "evidence_coverage",
            "report_sections",
            "report_validation",
            "warnings",
            "errors",
            "node_execution_records",
            "retry_counters",
            "artifacts",
            "final_result",
        }

        self.assertEqual(set(CompanyResearchState.__annotations__), expected_fields)
        self.assertEqual(len(CompanyResearchState.__annotations__), 24)

    def test_state_operation_groups_are_disjoint(self) -> None:
        replace = set(STATE_REPLACE_FIELDS)
        append = set(STATE_APPEND_FIELDS)
        upsert = set(STATE_UPSERT_FIELDS)
        counter = set(STATE_COUNTER_FIELDS)

        self.assertTrue(replace.isdisjoint(append))
        self.assertTrue(replace.isdisjoint(upsert))
        self.assertTrue(replace.isdisjoint(counter))
        self.assertTrue(append.isdisjoint(upsert))
        self.assertTrue(append.isdisjoint(counter))
        self.assertTrue(upsert.isdisjoint(counter))
        self.assertEqual(len(replace | append | upsert | counter), 24)

    def test_shared_state_is_json_serializable(self) -> None:
        sample_state: CompanyResearchState = {
            "state_version": "1.0",
            "execution_context": ExecutionContext(
                execution_id="exec_1",
                created_at="2026-07-23T00:00:00Z",
            ),
            "request": ResearchRequest(company_name="Apple Inc.", ticker="AAPL"),
            "runtime_config": RuntimeConfig(),
            "resolved_company": ResolvedCompany(company_name="Apple Inc.", ticker="AAPL"),
            "research_plan": ResearchPlan(company_name="Apple Inc."),
            "documents": [
                DocumentRecord(
                    document_id="doc_1",
                    company_name="Apple Inc.",
                    source_id="source_1",
                    document_type="sec_filing",
                )
            ],
            "sources": [
                SourceRecord(
                    source_id="source_1",
                    company_name="Apple Inc.",
                    provider_name="SEC EDGAR",
                    authority_level="primary",
                    acquired_at="2026-07-23T00:00:00Z",
                )
            ],
            "evidence": [
                EvidenceRecord(
                    evidence_id="evidence_1",
                    company_name="Apple Inc.",
                    source_id="source_1",
                    claim="Apple reported revenue growth.",
                    evidence_classification="regulatory",
                )
            ],
            "rejected_evidence": [
                RejectedEvidenceRecord(
                    rejected_evidence_id="rejected_1",
                    company_name="Apple Inc.",
                    source_id="source_1",
                    rejected_text="Unsupported claim.",
                    rejection_reason="unsupported",
                )
            ],
            "financial_metrics": [
                FinancialMetric(
                    metric_id="metric_1",
                    company_name="Apple Inc.",
                    metric_name="Revenue",
                    value=100.0,
                    period="2025-Q4",
                    source_id="source_1",
                )
            ],
            "news_events": [
                NewsEvent(
                    event_id="news_1",
                    company_name="Apple Inc.",
                    title="Apple announces results",
                    published_at="2026-07-23",
                    source_id="source_1",
                )
            ],
            "market_findings": [
                MarketFinding(
                    finding_id="finding_1",
                    company_name="Apple Inc.",
                    title="Market context",
                    source_id="source_1",
                )
            ],
            "rag_results": [
                RAGResult(
                    result_id="rag_1",
                    company_name="Apple Inc.",
                    document_id="doc_1",
                    chunk_id="chunk_1",
                    source_id="source_1",
                    text="Relevant excerpt.",
                )
            ],
            "evidence_conflicts": [
                EvidenceConflict(
                    conflict_id="conflict_1",
                    company_name="Apple Inc.",
                    source_ids=["source_1", "source_2"],
                    description="Conflicting revenue figures.",
                )
            ],
            "evidence_coverage": EvidenceCoverage(
                coverage_status="sufficient",
                covered_sections=["financial performance"],
            ),
            "report_sections": [
                ReportSection(
                    section_id="section_1",
                    title="Executive Summary",
                    order=1,
                    content="Summary content.",
                )
            ],
            "report_validation": ReportValidationResult(status="valid"),
            "warnings": [WorkflowWarning(code="warning_1", message="Optional source unavailable.")],
            "errors": [WorkflowError(code="error_1", message="Required source failed.")],
            "node_execution_records": [
                NodeExecutionRecord(node_name="initialize_request", status="completed")
            ],
            "retry_counters": {"repair_report": 0},
            "artifacts": [
                ArtifactRecord(artifact_id="artifact_1", artifact_type="markdown", path="outputs/report.md")
            ],
            "final_result": ExecutionResult(execution_id="exec_1", status="completed"),
        }

        def serialize(value: object) -> object:
            if is_dataclass(value):
                return asdict(value)
            if isinstance(value, list):
                return [serialize(item) for item in value]
            if isinstance(value, dict):
                return {key: serialize(item) for key, item in value.items()}
            return value

        json.dumps({key: serialize(value) for key, value in sample_state.items()})
