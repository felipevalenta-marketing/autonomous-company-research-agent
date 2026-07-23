"""Research planning models."""

from __future__ import annotations

from dataclasses import dataclass, field


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class ResearchTask:
    """Single task in the research plan."""

    task_id: str
    title: str
    required: bool = True
    description: str | None = None
    source_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.task_id, "task_id")
        _require_text(self.title, "title")


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    """Bounded plan for a research execution."""

    company_name: str
    version: str = "1.0"
    generated_at: str | None = None
    tasks: list[ResearchTask] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.company_name, "company_name")
        _require_text(self.version, "version")

