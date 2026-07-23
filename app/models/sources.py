"""Source lineage models."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Canonical source metadata and provenance."""

    source_id: str
    company_name: str
    provider_name: str
    authority_level: str
    acquired_at: str
    source_url: str | None = None
    raw_reference: str | None = None
    document_id: str | None = None
    payload_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.provider_name, "provider_name")
        _require_text(self.authority_level, "authority_level")
        _require_text(self.acquired_at, "acquired_at")

