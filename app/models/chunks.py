"""Canonical document chunk model."""

from __future__ import annotations

from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    return value


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """Deterministic document chunk metadata."""

    chunk_id: str
    document_id: str
    source_id: str
    company_name: str
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    content_checksum: str
    document_type: str
    source_url: str | None = None
    filing_type: str | None = None
    filing_date: str | None = None
    fiscal_period: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.source_id, "source_id")
        _require_text(self.company_name, "company_name")
        _require_text(self.text, "text")
        _require_text(self.content_checksum, "content_checksum")
        _require_text(self.document_type, "document_type")

        chunk_index = _require_int(self.chunk_index, "chunk_index")
        start_offset = _require_int(self.start_offset, "start_offset")
        end_offset = _require_int(self.end_offset, "end_offset")
        if chunk_index < 0:
            raise ValueError("chunk_index must be zero or positive.")
        if start_offset < 0:
            raise ValueError("start_offset must be zero or positive.")
        if end_offset <= start_offset:
            raise ValueError("end_offset must be greater than start_offset.")

        object.__setattr__(self, "source_url", _normalize_optional_text(self.source_url))
        object.__setattr__(self, "filing_type", _normalize_optional_text(self.filing_type))
        object.__setattr__(self, "filing_date", _normalize_optional_text(self.filing_date))
        object.__setattr__(self, "fiscal_period", _normalize_optional_text(self.fiscal_period))
