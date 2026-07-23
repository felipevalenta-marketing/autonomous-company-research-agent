"""Report and validation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ReportValidationStatus = Literal[
    "valid",
    "valid_with_warnings",
    "invalid_repairable",
    "invalid_non_repairable",
]


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class ReportSection:
    """Single report section."""

    section_id: str
    title: str
    order: int
    content: str
    citations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.section_id, "section_id")
        _require_text(self.title, "title")
        _require_text(self.content, "content")
        if self.order < 0:
            raise ValueError("order must be zero or positive.")


@dataclass(frozen=True, slots=True)
class ReportValidationResult:
    """Validation verdict for a generated report."""

    status: ReportValidationStatus
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validated_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "valid",
            "valid_with_warnings",
            "invalid_repairable",
            "invalid_non_repairable",
        }:
            raise ValueError("status must be a canonical report validation status.")

