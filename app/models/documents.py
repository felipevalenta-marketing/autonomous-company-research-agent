"""Document lineage models."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Canonical document metadata and processing state."""

    document_id: str
    company_name: str
    source_id: str
    document_type: str
    title: str | None = None
    content: str | None = None
    storage_path: str | None = None
    source_url: str | None = None
    filing_type: str | None = None
    filing_date: str | None = None
    fiscal_period: str | None = None
    extraction_status: str = "pending"
    chunk_count: int = 0

    def __post_init__(self) -> None:
        _require_text(self.document_id, "document_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.source_id, "source_id")
        _require_text(self.document_type, "document_type")
        if self.chunk_count < 0:
            raise ValueError("chunk_count must be zero or positive.")

