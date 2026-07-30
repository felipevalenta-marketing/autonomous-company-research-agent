"""Workflow state and error contracts for the LangGraph foundation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from app.models.company import ResolvedCompany

WorkflowStatus = Literal["initialized", "resolving_company", "company_resolved", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class ResearchWorkflowError:
    """Immutable, service-local workflow error record."""

    code: str
    message: str
    details: tuple[tuple[str, str], ...] = ()


class ResearchWorkflowState(TypedDict, total=False):
    """Minimal graph state for the research workflow foundation."""

    research_query: str
    company_input: str
    resolved_company: ResolvedCompany | None
    workflow_status: WorkflowStatus
    current_stage: WorkflowStatus
    errors: tuple[ResearchWorkflowError, ...]
