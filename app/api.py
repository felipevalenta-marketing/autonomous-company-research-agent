"""Public ASGI adapter exposing the research workflow to n8n."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
import os
import logging
from typing import Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.clients.openai_embeddings_client import OpenAIEmbeddingsClientError
from app.clients.pinecone_client import PineconeClientError
from app.clients.sec_client import SecClientError
from app.n8n_runner import build_application_dependencies
from app.services.company_resolution_service import CompanyResolutionError
from app.services.embedding_service import EmbeddingServiceError
from app.services.evidence_assembly_service import EvidenceAssemblyError
from app.services.rag_query_service import RAGQueryError
from app.services.workflow_integration_service import (
    WorkflowIntegrationConsistencyError,
    WorkflowIntegrationError,
    WorkflowIntegrationInputError,
    run_completed_workflow,
)
from app.services.workflow_output_service import WorkflowOutputError
from app.services.workflow_output_service import build_workflow_output
from app.settings import Settings, load_settings
from app.utils.logging import configure_logging

SERVICE_NAME = "autonomous-company-research-agent"
_LOGGER = logging.getLogger(__name__)
_LOGGER.propagate = True


@dataclass(frozen=True, slots=True)
class NormalizedResearchRequest:
    """Validated, normalized request payload for the research endpoint."""

    company: str
    ticker: str
    cik: str
    query: str


class ResearchRequestValidationError(ValueError):
    """Raised when the research request payload is invalid."""


def create_app(
    *,
    settings_loader: Callable[[], Settings] = load_settings,
    dependencies_factory: Callable[..., object] = build_application_dependencies,
) -> Starlette:
    """Create the ASGI application without constructing provider clients for health checks."""

    configure_logging()
    settings = settings_loader()

    async def health(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "ok", "service": SERVICE_NAME}, status_code=200)

    async def deployment_info(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "ok", "service": SERVICE_NAME, "deployment": _deployment_metadata()}, status_code=200)

    async def research(request: Request) -> JSONResponse:
        _log_research_request_received()
        if not _is_authorized(request.headers.get("X-API-Key"), settings.agent_api_key):
            return _unauthorized_response()

        try:
            payload = await _read_json_payload(request)
            normalized_request = _normalize_research_request(payload)
        except ResearchRequestValidationError as exc:
            _log_research_request_failure(
                stage="request_validation",
                exc=exc,
                response_status=400,
            )
            return _invalid_request_response()

        try:
            final_state = await run_in_threadpool(
                _execute_research_request,
                settings,
                dependencies_factory,
                normalized_request,
            )
        except ResearchRequestValidationError as exc:
            _log_research_request_failure(
                stage="request_validation",
                exc=exc,
                response_status=400,
            )
            return _invalid_request_response()
        except (
            CompanyResolutionError,
            EmbeddingServiceError,
            EvidenceAssemblyError,
            OpenAIEmbeddingsClientError,
            PineconeClientError,
            RAGQueryError,
            SecClientError,
        ) as exc:
            _log_research_request_failure(
                stage="workflow_execution",
                exc=exc,
                response_status=502,
            )
            return _provider_failure_response()
        except (WorkflowOutputError, WorkflowIntegrationError, WorkflowIntegrationInputError, WorkflowIntegrationConsistencyError) as exc:
            _log_research_request_failure(
                stage="workflow_output",
                exc=exc,
                response_status=500,
            )
            return _internal_error_response()
        except Exception as exc:
            _log_research_request_failure(
                stage="unexpected",
                exc=exc,
                response_status=500,
            )
            return _internal_error_response()

        retrieval_failure = _workflow_retrieval_failure(final_state)
        if retrieval_failure is not None:
            error_type, cause_type = retrieval_failure
            _log_research_request_failure(
                stage="workflow_execution",
                error_type=error_type,
                cause_type=cause_type,
                response_status=502,
            )
            return _provider_failure_response()

        try:
            workflow_output = build_workflow_output(final_state)
            result = run_completed_workflow(workflow_output)
        except WorkflowOutputError as exc:
            if _workflow_failure_has_retrieval_cause(exc):
                cause = getattr(exc, "__cause__", None)
                _log_research_request_failure(
                    stage="workflow_output",
                    error_type=type(exc).__name__,
                    cause_type=type(cause).__name__ if isinstance(cause, Exception) else "None",
                    response_status=502,
                )
                return _provider_failure_response()
            _log_research_request_failure(
                stage="workflow_output",
                exc=exc,
                response_status=500,
            )
            return _internal_error_response()
        except WorkflowIntegrationError as exc:
            if _workflow_failure_has_retrieval_cause(exc):
                cause = getattr(exc, "__cause__", None)
                _log_research_request_failure(
                    stage="workflow_output",
                    error_type=type(exc).__name__,
                    cause_type=type(cause).__name__ if isinstance(cause, Exception) else "None",
                    response_status=502,
                )
                return _provider_failure_response()
            _log_research_request_failure(
                stage="workflow_output",
                exc=exc,
                response_status=500,
            )
            return _internal_error_response()
        except Exception as exc:
            _log_research_request_failure(
                stage="unexpected",
                exc=exc,
                response_status=500,
            )
            return _internal_error_response()

        return JSONResponse(result, status_code=200)

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/deployment-info", deployment_info, methods=["GET"]),
            Route("/research", research, methods=["POST"]),
        ]
    )
    app.state.settings = settings
    app.state.dependencies_factory = dependencies_factory
    return app


app = create_app()


def _execute_research_request(
    settings: Settings,
    dependencies_factory: Callable[..., object],
    normalized_request: NormalizedResearchRequest,
) -> object:
    dependencies = dependencies_factory(
        settings,
        company=normalized_request.company,
        resolved_ticker=normalized_request.ticker,
        resolved_cik=normalized_request.cik,
    )
    cleanup = getattr(dependencies, "cleanup", None)
    try:
        return dependencies.workflow.invoke(
            {
                "research_query": normalized_request.query,
                "company_input": normalized_request.company,
            }
        )
    finally:
        if callable(cleanup):
            cleanup()


def _normalize_research_request(payload: object) -> NormalizedResearchRequest:
    if not isinstance(payload, dict):
        raise ResearchRequestValidationError("research request payload must be a JSON object.")

    company = _normalize_text_field(payload.get("company"), "company")
    ticker = _normalize_ticker_field(payload.get("ticker"))
    cik = _normalize_cik_field(payload.get("cik"))
    query = _normalize_text_field(payload.get("query"), "query")
    return NormalizedResearchRequest(company=company, ticker=ticker, cik=cik, query=query)


def _normalize_text_field(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ResearchRequestValidationError(f"{field_name} must be a non-empty string.")
    normalized = value.strip()
    if not normalized:
        raise ResearchRequestValidationError(f"{field_name} must be a non-empty string.")
    return normalized


def _normalize_ticker_field(value: object) -> str:
    ticker = _normalize_text_field(value, "ticker")
    return ticker.upper()


def _normalize_cik_field(value: object) -> str:
    cik = _normalize_text_field(value, "cik")
    if not cik.isdigit() or int(cik) <= 0:
        raise ResearchRequestValidationError("cik must be a positive numeric string.")
    return f"{int(cik):010d}"


async def _read_json_payload(request: Request) -> object:
    try:
        return await request.json()
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ResearchRequestValidationError("research request payload must be valid JSON.") from exc


def _is_authorized(provided_key: str | None, expected_key: str | None) -> bool:
    if not isinstance(provided_key, str) or not isinstance(expected_key, str):
        return False
    expected = expected_key.strip()
    if not expected:
        return False
    return compare_digest(provided_key.strip(), expected)


def _invalid_request_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "failed",
            "error_code": "INVALID_RESEARCH_REQUEST",
            "message": "Company, ticker, CIK and research query are required.",
        },
        status_code=400,
    )


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "failed",
            "error_code": "UNAUTHORIZED",
            "message": "Invalid API credentials.",
        },
        status_code=401,
    )


def _provider_failure_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "failed",
            "error_code": "RESEARCH_RETRIEVAL_FAILED",
            "message": "Research retrieval failed.",
        },
        status_code=502,
    )


def _internal_error_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "failed",
            "error_code": "INTERNAL_RESEARCH_ERROR",
            "message": "The research workflow could not be completed.",
        },
        status_code=500,
    )


def _log_research_request_failure(
    *,
    stage: str,
    response_status: int,
    exc: Exception | None = None,
    error_type: str | None = None,
    cause_type: str | None = None,
) -> None:
    if exc is not None:
        error_type = type(exc).__name__
        cause = getattr(exc, "__cause__", None)
        cause_type = type(cause).__name__ if isinstance(cause, Exception) else "None"
    if error_type is None:
        error_type = "None"
    _LOGGER.warning(
        "research_request_failed stage=%s error_type=%s cause_type=%s response_status=%s",
        stage,
        error_type,
        cause_type or "None",
        response_status,
    )


def _log_research_request_received() -> None:
    metadata = _deployment_metadata()
    _LOGGER.info(
        "research_request_received route=/research service_name=%s environment=%s commit=%s",
        metadata["service_name"],
        metadata["environment"],
        metadata["commit"],
    )


def _deployment_metadata() -> dict[str, str]:
    service_name = _safe_env_value("RAILWAY_SERVICE_NAME", default="local")
    environment = _safe_env_value("RAILWAY_ENVIRONMENT_NAME", default="local")
    commit = _short_commit_sha(os.getenv("RAILWAY_GIT_COMMIT_SHA"))
    return {
        "service_name": service_name,
        "environment": environment,
        "commit": commit,
    }


def _safe_env_value(name: str, *, default: str) -> str:
    value = os.getenv(name)
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    return normalized or default


def _short_commit_sha(value: str | None) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip()
    if not normalized:
        return "unknown"
    return normalized[:8]


def _workflow_retrieval_failure(final_state: object) -> tuple[str, str | None] | None:
    if not isinstance(final_state, dict):
        return None
    if final_state.get("workflow_status") != "failed":
        return None

    errors = final_state.get("errors")
    if not isinstance(errors, tuple):
        return None

    for error in errors:
        code = getattr(error, "code", None)
        if code not in {
            "RAGQueryError",
            "RAGQueryResponseConsistencyError",
            "RAGQueryNamespaceConsistencyError",
            "RAGEmbeddingError",
            "RAGRetrievalError",
        }:
            continue
        details = getattr(error, "details", ())
        if not isinstance(details, tuple):
            continue

        stage = None
        cause_type = None
        detail_error_type = None
        for detail in details:
            if not isinstance(detail, tuple) or len(detail) != 2:
                continue
            key, value = detail
            if key == "stage" and value == "retrieving_research":
                stage = "retrieving_research"
            elif key == "error_type" and isinstance(value, str):
                normalized = value.strip()
                if normalized:
                    detail_error_type = normalized
                if normalized and not normalized.startswith("RAG"):
                    cause_type = normalized

        if stage == "retrieving_research":
            if code == "RAGQueryError" and detail_error_type in {
                "RAGQueryResponseConsistencyError",
                "RAGQueryNamespaceConsistencyError",
            }:
                return detail_error_type, None
            return str(code), cause_type
    return None


def _workflow_failure_has_retrieval_cause(exc: Exception) -> bool:
    current: Exception | None = exc
    seen: set[int] = set()
    retrieval_types = {
        "EmbeddingServiceError",
        "OpenAIEmbeddingsTransportError",
        "OpenAIEmbeddingsTimeoutError",
        "OpenAIEmbeddingsRateLimitError",
        "PineconeClientError",
        "PineconeTransportError",
        "PineconeTimeoutError",
        "PineconeRateLimitError",
        "RAGEmbeddingError",
        "RAGQueryError",
        "RAGRetrievalError",
        "VectorQueryError",
    }

    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in retrieval_types:
            return True
        cause = getattr(current, "__cause__", None)
        current = cause if isinstance(cause, Exception) else None
    return False
