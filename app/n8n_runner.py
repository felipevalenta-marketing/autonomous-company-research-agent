"""Executable adapter for external automation to consume completed workflow output."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from functools import partial
from typing import Callable, Sequence

from app.clients.openai_embeddings_client import OpenAIEmbeddingsClient
from app.clients.pinecone_client import PineconeClient
from app.clients.sec_client import SecClient
from app.config.constants import OPENAI_BASE_URL, OPENAI_DEFAULT_EMBEDDING_MODEL
from app.config.defaults import build_pinecone_config, build_runtime_config
from app.graph.workflow import build_research_workflow
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


@dataclass(frozen=True, slots=True)
class _RunnerDependencies:
    workflow: object
    build_workflow_output: Callable[[object], WorkflowOutput]
    run_completed_workflow: Callable[[WorkflowOutput], dict[str, object]]


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

    try:
        settings = settings_loader()
        if dependencies_factory is None:
            dependencies_factory = _build_application_dependencies
        dependencies = dependencies_factory(settings, args)
        final_state = dependencies.workflow.invoke(
            {
                "research_query": args.query,
                "company_input": args.company,
            }
        )
        workflow_output = dependencies.build_workflow_output(final_state)
        payload = dependencies.run_completed_workflow(workflow_output)
    except (WorkflowOutputError, WorkflowIntegrationError, WorkflowIntegrationInputError, WorkflowIntegrationConsistencyError) as exc:
        print(_safe_error_message(exc), file=stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive boundary
        print(_safe_error_message(exc), file=stderr)
        return 1

    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the completed company-research workflow and emit JSON.")
    parser.add_argument("--company")
    parser.add_argument("--query")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--max-evidence", type=int, default=None)
    return parser.parse_args(argv)


def _validate_cli_args(args: argparse.Namespace) -> str | None:
    if not isinstance(args.company, str) or not args.company.strip():
        return "error: --company must be a non-blank string."
    if not isinstance(args.query, str) or not args.query.strip():
        return "error: --query must be a non-blank string."
    if args.top_k is not None and (isinstance(args.top_k, bool) or args.top_k <= 0):
        return "error: --top-k must be a positive integer when provided."
    if args.max_evidence is not None and (isinstance(args.max_evidence, bool) or args.max_evidence <= 0):
        return "error: --max-evidence must be a positive integer when provided."
    return None


def _build_application_dependencies(settings: Settings, args: argparse.Namespace) -> _RunnerDependencies:
    runtime_config = build_runtime_config(settings)
    pinecone_config = build_pinecone_config(settings)
    rag_top_k = args.top_k if args.top_k is not None else pinecone_config.max_query_top_k
    max_evidence = args.max_evidence if args.max_evidence is not None else _DEFAULT_MAX_EVIDENCE

    openai_client = OpenAIEmbeddingsClient(
        runtime_config,
        base_url=settings.openai_base_url or OPENAI_BASE_URL,
        default_model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
    )
    sec_client = SecClient(runtime_config)
    pinecone_client = PineconeClient(runtime_config, pinecone_config)

    embedding_service = partial(
        embed_texts,
        embedding_client=openai_client,
        model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
        expected_dimension=pinecone_config.vector_dimension,
    )

    workflow = build_research_workflow(
        company_resolution_dependency=resolve_company,
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
    )


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, WorkflowOutputError):
        return "error: completed workflow output could not be built."
    if isinstance(exc, WorkflowIntegrationError):
        return "error: workflow integration failed."
    return "error: workflow execution failed."


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
