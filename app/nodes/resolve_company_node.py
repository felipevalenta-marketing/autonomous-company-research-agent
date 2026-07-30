"""Company-resolution node for the research workflow foundation."""

from __future__ import annotations

from collections.abc import Callable

from app.graph.state import ResearchWorkflowError, ResearchWorkflowState
from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.request import ResearchRequest
from app.services.company_resolution_service import CompanyResolutionError, SecTickerClientProtocol

CompanyResolutionDependency = Callable[[ResearchRequest, RuntimeConfig, SecTickerClientProtocol], ResolvedCompany]

_RESOLVING_STAGE = "resolving_company"
_FAILED_STAGE = "failed"


def build_resolve_company_node(
    company_resolution_dependency: CompanyResolutionDependency,
    runtime_config: RuntimeConfig,
    sec_client: SecTickerClientProtocol,
):
    """Build the node that delegates to the approved company-resolution service."""

    def resolve_company(state: ResearchWorkflowState) -> ResearchWorkflowState:
        company_input = state.get("company_input")
        if not isinstance(company_input, str) or not company_input.strip():
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_company_input",
                        message="company_input must be a non-empty string.",
                    ),
                ),
            }

        try:
            resolved_company = company_resolution_dependency(
                ResearchRequest(company_name=company_input),
                runtime_config,
                sec_client,
            )
        except CompanyResolutionError as exc:
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code=exc.__class__.__name__,
                        message=str(exc),
                        details=(("stage", _RESOLVING_STAGE),),
                    ),
                ),
            }
        except Exception as exc:  # pragma: no cover - defensive boundary mapping
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="company_resolution_failure",
                        message="Company resolution failed.",
                        details=(
                            ("stage", _RESOLVING_STAGE),
                            ("error_type", exc.__class__.__name__),
                        ),
                    ),
                ),
            }

        if not isinstance(resolved_company, ResolvedCompany):
            return {
                "workflow_status": _FAILED_STAGE,
                "current_stage": _FAILED_STAGE,
                "errors": (
                    ResearchWorkflowError(
                        code="invalid_resolved_company",
                        message="Company resolution returned an invalid company record.",
                        details=(("stage", _RESOLVING_STAGE),),
                    ),
                ),
            }

        return {
            "resolved_company": resolved_company,
            "workflow_status": _RESOLVING_STAGE,
            "current_stage": _RESOLVING_STAGE,
            "errors": (),
        }

    return resolve_company
