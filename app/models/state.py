"""Canonical shared application state contract."""

from __future__ import annotations

from typing import TypedDict

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

STATE_REPLACE_FIELDS: tuple[str, ...] = (
    "state_version",
    "execution_context",
    "request",
    "runtime_config",
    "resolved_company",
    "research_plan",
    "evidence_coverage",
    "report_validation",
    "final_result",
)

STATE_APPEND_FIELDS: tuple[str, ...] = (
    "evidence",
    "rejected_evidence",
    "financial_metrics",
    "news_events",
    "market_findings",
    "rag_results",
    "evidence_conflicts",
    "warnings",
    "errors",
    "node_execution_records",
    "artifacts",
)

STATE_UPSERT_FIELDS: tuple[str, ...] = (
    "documents",
    "sources",
    "report_sections",
)

STATE_COUNTER_FIELDS: tuple[str, ...] = ("retry_counters",)


class CompanyResearchState(TypedDict, total=False):
    """Canonical shared state used by the workflow."""

    state_version: str
    execution_context: ExecutionContext
    request: ResearchRequest
    runtime_config: RuntimeConfig
    resolved_company: ResolvedCompany | None
    research_plan: ResearchPlan | None
    documents: list[DocumentRecord]
    sources: list[SourceRecord]
    evidence: list[EvidenceRecord]
    rejected_evidence: list[RejectedEvidenceRecord]
    financial_metrics: list[FinancialMetric]
    news_events: list[NewsEvent]
    market_findings: list[MarketFinding]
    rag_results: list[RAGResult]
    evidence_conflicts: list[EvidenceConflict]
    evidence_coverage: EvidenceCoverage | None
    report_sections: list[ReportSection]
    report_validation: ReportValidationResult | None
    warnings: list[WorkflowWarning]
    errors: list[WorkflowError]
    node_execution_records: list[NodeExecutionRecord]
    retry_counters: dict[str, int]
    artifacts: list[ArtifactRecord]
    final_result: ExecutionResult | None

