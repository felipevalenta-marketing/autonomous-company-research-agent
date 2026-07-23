"""Evidence, conflict, and coverage models."""

from __future__ import annotations

from dataclasses import dataclass, field


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Accepted evidence item."""

    evidence_id: str
    company_name: str
    source_id: str
    claim: str
    evidence_classification: str
    extracted_span: str | None = None
    timestamp_context: str | None = None
    document_id: str | None = None
    period: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "evidence_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.source_id, "source_id")
        _require_text(self.claim, "claim")
        _require_text(self.evidence_classification, "evidence_classification")


@dataclass(frozen=True, slots=True)
class RejectedEvidenceRecord:
    """Evidence candidate rejected during normalization or retrieval."""

    rejected_evidence_id: str
    company_name: str
    source_id: str
    rejected_text: str
    rejection_reason: str
    document_id: str | None = None
    evidence_classification: str | None = None
    timestamp_context: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.rejected_evidence_id, "rejected_evidence_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.source_id, "source_id")
        _require_text(self.rejected_text, "rejected_text")
        _require_text(self.rejection_reason, "rejection_reason")


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    """Explicit conflict between evidence items."""

    conflict_id: str
    company_name: str
    source_ids: list[str] = field(default_factory=list)
    description: str = ""
    severity: str = "medium"
    resolution_status: str = "unresolved"

    def __post_init__(self) -> None:
        _require_text(self.conflict_id, "conflict_id")
        _require_text(self.company_name, "company_name")
        if not self.source_ids:
            raise ValueError("source_ids must not be empty.")
        _require_text(self.description, "description")
        _require_text(self.severity, "severity")
        _require_text(self.resolution_status, "resolution_status")


@dataclass(frozen=True, slots=True)
class EvidenceCoverage:
    """Coverage verdict for a report section set."""

    coverage_status: str
    covered_sections: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.coverage_status, "coverage_status")

