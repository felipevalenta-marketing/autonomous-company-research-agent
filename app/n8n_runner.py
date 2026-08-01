"""Executable adapter for external automation to consume completed workflow output."""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from typing import Callable, Sequence
from types import SimpleNamespace

from app.clients.openai_embeddings_client import OpenAIEmbeddingsClient
from app.clients.pinecone_client import PineconeClient
from app.clients.sec_client import SecClient
from app.config.constants import OPENAI_BASE_URL, OPENAI_DEFAULT_EMBEDDING_MODEL
from app.config.defaults import build_pinecone_config, build_runtime_config
from app.graph.workflow import build_research_workflow
from app.models.company import ResolvedCompany
from app.graph.state import ResearchWorkflowError
from app.services.embedding_service import EmbeddingServiceResult, embed_texts
from app.services.company_resolution_service import resolve_company
from app.services.workflow_integration_service import (
    WorkflowIntegrationConsistencyError,
    WorkflowIntegrationError,
    WorkflowIntegrationInputError,
    run_completed_workflow,
)
from app.services.workflow_output_service import WorkflowOutput, WorkflowOutputError, build_workflow_output
from app.settings import Settings, load_settings

_DEFAULT_MAX_EVIDENCE = 3
_OVERRIDE_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


@dataclass(frozen=True, slots=True)
class _RunnerDependencies:
    workflow: object
    build_workflow_output: Callable[[object], WorkflowOutput]
    run_completed_workflow: Callable[[WorkflowOutput], dict[str, object]]
    cleanup: Callable[[], None] | None = None


def build_application_dependencies(
    settings: Settings,
    *,
    company: str,
    resolved_ticker: str,
    resolved_cik: str,
    top_k: int | None = None,
    max_evidence: int | None = None,
) -> _RunnerDependencies:
    """Build the reusable application dependency set for HTTP or CLI entry points."""

    args = SimpleNamespace(
        company=company,
        query="",
        resolved_ticker=resolved_ticker,
        resolved_cik=resolved_cik,
        top_k=top_k,
        max_evidence=max_evidence,
    )
    return _build_application_dependencies(settings, args)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Settings] = load_settings,
    dependencies_factory: Callable[[Settings, argparse.Namespace], _RunnerDependencies] | None = None,
    stdout = sys.stdout,
    stderr = sys.stderr,
) -> int:
    """Run the completed workflow and emit a single JSON payload to stdout."""

    try:
        args = _parse_args(argv)
    except SystemExit as exc:  # pragma: no cover - argparse help / parse failure
        return int(exc.code or 2)

    input_error = _validate_cli_args(args)
    if input_error is not None:
        print(input_error, file=stderr)
        return 2

    cleanup: Callable[[], None] | None = None
    try:
        settings = settings_loader()
        if dependencies_factory is None:
            dependencies_factory = _build_application_dependencies
        dependencies = dependencies_factory(settings, args)
        cleanup = getattr(dependencies, "cleanup", None)
        final_state = dependencies.workflow.invoke(
            {
                "research_query": args.query,
                "company_input": args.company,
            }
        )
        if getattr(args, "debug", False) and _workflow_state_failed(final_state):
            _emit_debug_workflow_state(final_state, stderr=stderr)
        if _workflow_failed_due_to_sec_transport(final_state):
            print("error: SEC transport failed after retry.", file=stderr)
            return 1
        workflow_output = dependencies.build_workflow_output(final_state)
        payload = dependencies.run_completed_workflow(workflow_output)
    except (WorkflowOutputError, WorkflowIntegrationError, WorkflowIntegrationInputError, WorkflowIntegrationConsistencyError) as exc:
        if getattr(args, "debug", False):
            traceback.print_exc(file=stderr)
            print(
                f"error: completed workflow output could not be built. Reason: {type(exc).__name__}: {_safe_error_message(exc)}",
                file=stderr,
            )
            return 1
        print(_safe_error_message(exc), file=stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive boundary
        if getattr(args, "debug", False):
            traceback.print_exc(file=stderr)
            print(
                f"error: workflow execution failed. Reason: {type(exc).__name__}: {_safe_error_message(exc)}",
                file=stderr,
            )
            return 1
        print(_safe_error_message(exc), file=stderr)
        return 1
    finally:
        if callable(cleanup):
            cleanup()

    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the completed company-research workflow and emit JSON.")
    parser.add_argument("--company")
    parser.add_argument("--query")
    parser.add_argument("--resolved-ticker")
    parser.add_argument("--resolved-cik")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--max-evidence", type=int, default=None)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def _validate_cli_args(args: argparse.Namespace) -> str | None:
    if not isinstance(args.company, str) or not args.company.strip():
        return "error: --company must be a non-blank string."
    if not isinstance(args.query, str) or not args.query.strip():
        return "error: --query must be a non-blank string."
    ticker_supplied = args.resolved_ticker is not None
    cik_supplied = args.resolved_cik is not None
    if ticker_supplied != cik_supplied:
        return "error: resolved ticker and CIK must be provided together."
    if ticker_supplied and cik_supplied:
        try:
            _build_override_resolved_company(args)
        except ValueError as exc:
            return f"error: {exc}"
    if args.top_k is not None and (isinstance(args.top_k, bool) or args.top_k <= 0):
        return "error: --top-k must be a positive integer when provided."
    if args.max_evidence is not None and (isinstance(args.max_evidence, bool) or args.max_evidence <= 0):
        return "error: --max-evidence must be a positive integer when provided."
    return None


def _build_application_dependencies(settings: Settings, args: argparse.Namespace) -> _RunnerDependencies:
    stack = ExitStack()
    try:
        runtime_config = build_runtime_config(settings)
        pinecone_config = build_pinecone_config(settings)
        rag_top_k = args.top_k if args.top_k is not None else pinecone_config.max_query_top_k
        max_evidence = args.max_evidence if args.max_evidence is not None else _DEFAULT_MAX_EVIDENCE
        override_resolved_company = _build_override_resolved_company(args) if _has_complete_company_override(args) else None

        openai_client = OpenAIEmbeddingsClient(
            runtime_config,
            base_url=settings.openai_base_url or OPENAI_BASE_URL,
            default_model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
        )
        stack.callback(openai_client.close)
        sec_client = None if override_resolved_company is not None else SecClient(runtime_config)
        if sec_client is not None:
            stack.callback(sec_client.close)
        pinecone_client = PineconeClient(runtime_config, pinecone_config)
        stack.callback(pinecone_client.close)

        embedding_service = partial(
            embed_texts,
            embedding_client=openai_client,
            model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
            expected_dimension=pinecone_config.vector_dimension,
        )

        company_resolution_dependency = (
            _build_override_company_resolution_dependency(override_resolved_company)
            if override_resolved_company is not None
            else resolve_company
        )

        workflow = build_research_workflow(
            company_resolution_dependency=company_resolution_dependency,
            runtime_config=runtime_config,
            sec_client=sec_client,
            embedding_service=embedding_service,
            vector_query_service=pinecone_client.query,
            rag_top_k=rag_top_k,
            max_evidence=max_evidence,
        )
        return _RunnerDependencies(
            workflow=workflow,
            build_workflow_output=build_workflow_output,
            run_completed_workflow=run_completed_workflow,
            cleanup=stack.close,
        )
    except Exception:
        stack.close()
        raise


def _has_complete_company_override(args: argparse.Namespace) -> bool:
    ticker_supplied = args.resolved_ticker is not None
    cik_supplied = args.resolved_cik is not None
    return ticker_supplied and cik_supplied


def _build_override_resolved_company(args: argparse.Namespace) -> ResolvedCompany:
    if not isinstance(args.company, str) or not args.company.strip():
        raise ValueError("--company must be a non-blank string.")
    ticker = _normalize_override_ticker(args.resolved_ticker)
    cik = _normalize_override_cik(args.resolved_cik)
    return ResolvedCompany(company_name=args.company, ticker=ticker, cik=cik)


def _build_override_company_resolution_dependency(resolved_company: ResolvedCompany):
    def resolve_company_override(request, runtime_config, sec_client):  # noqa: ANN001, ANN002, ANN003
        del request, runtime_config, sec_client
        return resolved_company

    return resolve_company_override


def _normalize_override_ticker(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("--resolved-ticker must be a non-blank string.")
    ticker = value.strip().upper()
    if not ticker:
        raise ValueError("--resolved-ticker must be a non-blank string.")
    if not _OVERRIDE_TICKER_PATTERN.fullmatch(ticker):
        raise ValueError("--resolved-ticker must be a valid ticker symbol.")
    return ticker


def _normalize_override_cik(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("--resolved-cik must be a non-blank numeric string.")
    cik = value.strip()
    if not cik:
        raise ValueError("--resolved-cik must be a non-blank numeric string.")
    if not cik.isdigit() or int(cik) <= 0:
        raise ValueError("--resolved-cik must be a positive numeric string.")
    return f"{int(cik):010d}"


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, WorkflowOutputError):
        return "error: completed workflow output could not be built."
    if isinstance(exc, WorkflowIntegrationError):
        return "error: workflow integration failed."
    return "error: workflow execution failed."


def _emit_debug_workflow_state(final_state: object, *, stderr) -> None:  # noqa: ANN001
    print("DEBUG WORKFLOW STATE", file=stderr)
    if not isinstance(final_state, dict):
        print("workflow_status: <unavailable>", file=stderr)
        print("current_stage: <unavailable>", file=stderr)
        print("state_keys: <unavailable>", file=stderr)
        print("error_count: 0", file=stderr)
        return

    workflow_status = final_state.get("workflow_status")
    current_stage = final_state.get("current_stage")
    state_keys = ",".join(sorted(str(key) for key in final_state.keys()))
    errors = final_state.get("errors")
    error_items = errors if isinstance(errors, tuple) else ()

    print(f"workflow_status: {workflow_status}", file=stderr)
    print(f"current_stage: {current_stage}", file=stderr)
    print(f"state_keys: {state_keys}", file=stderr)
    print(f"error_count: {len(error_items)}", file=stderr)

    for index, error in enumerate(error_items, start=1):
        print(f"WORKFLOW ERROR {index}", file=stderr)
        if not isinstance(error, ResearchWorkflowError):
            print(f"class: {type(error).__name__}", file=stderr)
            continue

        print(f"code: {error.code}", file=stderr)
        print(f"message: {error.message}", file=stderr)
        details = getattr(error, "details", ())
        if not isinstance(details, tuple):
            continue
        for detail in details:
            if not isinstance(detail, tuple) or len(detail) != 2:
                continue
            detail_name, detail_value = detail
            if not isinstance(detail_name, str):
                continue
            safe_value = _debug_scalar_value(detail_value)
            if safe_value is None:
                continue
            if detail_name == "stage":
                print(f"stage: {safe_value}", file=stderr)
            elif detail_name == "error_type":
                print(f"error_type: {safe_value}", file=stderr)
            else:
                print(f"{detail_name}: {safe_value}", file=stderr)


def _debug_scalar_value(value: object) -> str | None:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float, str)) or value is None:
        return str(value)
    return None


def _workflow_failed_due_to_sec_transport(final_state: object) -> bool:
    if not isinstance(final_state, dict):
        return False
    if final_state.get("workflow_status") != "failed":
        return False
    errors = final_state.get("errors")
    if not isinstance(errors, tuple):
        return False
    for error in errors:
        if getattr(error, "code", None) == "company_resolution_failure":
            details = getattr(error, "details", ())
            for key, value in details:
                if key == "error_type" and value == "SecTransportError":
                    return True
    return False


def _workflow_state_failed(final_state: object) -> bool:
    return isinstance(final_state, dict) and final_state.get("workflow_status") == "failed"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
