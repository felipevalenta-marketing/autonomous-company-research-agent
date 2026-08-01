"""Executable adapter for bounded SEC-to-RAG ingestion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import ExitStack
from dataclasses import dataclass, replace
from functools import partial
from html.parser import HTMLParser
from typing import Callable, Sequence

import httpx

from app.clients.openai_embeddings_client import OpenAIEmbeddingsClient
from app.clients.pinecone_client import PineconeClient
from app.clients.sec_client import SecClient, SecTransportError
from app.config.constants import OPENAI_BASE_URL, OPENAI_DEFAULT_EMBEDDING_MODEL
from app.config.defaults import build_pinecone_config, build_runtime_config
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.models.execution import RuntimeConfig
from app.models.request import ResearchRequest
from app.services.chunk_embedding_service import ChunkEmbeddingError
from app.services.company_resolution_service import CompanyResolutionError, resolve_company
from app.services.document_chunking_service import DEFAULT_DOCUMENT_CHUNK_OVERLAP, DEFAULT_DOCUMENT_CHUNK_SIZE
from app.services.embedding_service import embed_texts
from app.services.rag_ingestion_service import RAGIngestionResult, ingest_documents
from app.services.sec_collection_service import SecCollectionError, collect_sec_documents
from app.services.vector_preparation_service import build_pinecone_namespace
from app.settings import Settings, load_settings

_ALLOWED_FILING_TYPES = {"10-K", "10-Q"}
_DEFAULT_FILING_TYPE = "10-K"
_DEFAULT_LIMIT = 1
_MAX_LIMIT = 3


@dataclass(frozen=True, slots=True)
class _RunnerDependencies:
    resolve_company: Callable[[str], ResolvedCompany]
    collect_sec_documents: Callable[[ResolvedCompany], tuple[DocumentRecord, ...]]
    load_document_content: Callable[[DocumentRecord], DocumentRecord]
    ingest_documents: Callable[[tuple[DocumentRecord, ...], ResolvedCompany], RAGIngestionResult]
    cleanup: Callable[[], None] | None = None


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Settings] = load_settings,
    dependencies_factory: Callable[[Settings, argparse.Namespace], _RunnerDependencies] | None = None,
    stdout=sys.stdout,
    stderr=sys.stderr,
) -> int:
    """Run bounded SEC ingestion and emit a single JSON summary."""

    try:
        args = _parse_args(argv)
    except SystemExit as exc:  # pragma: no cover - argparse help / parse failure
        return int(exc.code or 2)

    validation_error = _validate_cli_args(args)
    if validation_error is not None:
        print(validation_error, file=stderr)
        return 2

    cleanup: Callable[[], None] | None = None
    try:
        settings = settings_loader()
        if dependencies_factory is None:
            dependencies_factory = _build_application_dependencies
        dependencies = dependencies_factory(settings, args)
        cleanup = getattr(dependencies, "cleanup", None)
        limit = _parse_positive_int(args.limit, "--limit")

        resolved_company = dependencies.resolve_company(args.company)
        collected_documents = dependencies.collect_sec_documents(resolved_company)
        selected_documents = _select_documents(collected_documents, args.filing_type, limit)
        if not selected_documents:
            print("error: no eligible SEC filings were found for the requested filing type.", file=stderr)
            return 1

        loaded_documents = tuple(dependencies.load_document_content(document) for document in selected_documents)
        ingestion_result = dependencies.ingest_documents(loaded_documents, resolved_company)
        payload = _build_summary(
            resolved_company=resolved_company,
            filing_type=_normalize_filing_type(args.filing_type),
            selected_document_count=len(selected_documents),
            ingestion_result=ingestion_result,
        )
    except SecTransportError as exc:
        print(_safe_error_message(exc), file=stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive boundary
        print(_safe_error_message(exc), file=stderr)
        return 1
    finally:
        if callable(cleanup):
            cleanup()

    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded SEC-to-RAG ingestion and emit JSON.")
    parser.add_argument("--company")
    parser.add_argument("--filing-type", default=_DEFAULT_FILING_TYPE)
    parser.add_argument("--limit", default=str(_DEFAULT_LIMIT))
    parser.add_argument("--chunk-size", default=str(DEFAULT_DOCUMENT_CHUNK_SIZE))
    parser.add_argument("--overlap", default=str(DEFAULT_DOCUMENT_CHUNK_OVERLAP))
    return parser.parse_args(argv)


def _validate_cli_args(args: argparse.Namespace) -> str | None:
    if not isinstance(args.company, str) or not args.company.strip():
        return "error: --company must be a non-blank string."
    filing_type = _normalize_filing_type(args.filing_type)
    if filing_type not in _ALLOWED_FILING_TYPES:
        return "error: --filing-type must be one of: 10-K, 10-Q."
    try:
        limit = _parse_positive_int(args.limit, "--limit")
    except ValueError as exc:
        return f"error: {exc}"
    if limit > _MAX_LIMIT:
        return f"error: --limit must not exceed {_MAX_LIMIT}."
    try:
        chunk_size = _parse_positive_int(args.chunk_size, "--chunk-size")
    except ValueError as exc:
        return f"error: {exc}"
    try:
        overlap = _parse_nonnegative_int(args.overlap, "--overlap")
    except ValueError as exc:
        return f"error: {exc}"
    if overlap >= chunk_size:
        return "error: --overlap must be smaller than --chunk-size."
    return None


def _build_application_dependencies(settings: Settings, args: argparse.Namespace) -> _RunnerDependencies:
    stack = ExitStack()
    try:
        runtime_config = build_runtime_config(settings)
        pinecone_config = build_pinecone_config(settings)

        openai_client = OpenAIEmbeddingsClient(
            runtime_config,
            base_url=settings.openai_base_url or OPENAI_BASE_URL,
            default_model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
        )
        stack.callback(openai_client.close)
        sec_client = SecClient(runtime_config)
        stack.callback(sec_client.close)
        pinecone_client = PineconeClient(runtime_config, pinecone_config)
        stack.callback(pinecone_client.close)
        chunk_size = _parse_positive_int(args.chunk_size, "--chunk-size")
        overlap = _parse_nonnegative_int(args.overlap, "--overlap")

        def resolve_company_dependency(company_input: str) -> ResolvedCompany:
            return resolve_company(ResearchRequest(company_name=company_input), runtime_config, sec_client)

        def collect_sec_documents_dependency(resolved_company: ResolvedCompany) -> tuple[DocumentRecord, ...]:
            documents, _sources = collect_sec_documents(resolved_company, sec_client, runtime_config)
            return documents

        def load_document_content_dependency(document: DocumentRecord) -> DocumentRecord:
            return _ensure_document_content(document, runtime_config)

        def ingest_documents_dependency(
            documents: tuple[DocumentRecord, ...],
            resolved_company: ResolvedCompany,
        ) -> RAGIngestionResult:
            namespace = build_pinecone_namespace(resolved_company, pinecone_config.namespace_prefix)
            embedding_service = partial(
                embed_texts,
                embedding_client=openai_client,
                model=settings.openai_embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
                expected_dimension=pinecone_config.vector_dimension,
            )
            return ingest_documents(
                documents,
                embedding_service=embedding_service,
                pinecone_client=pinecone_client,
                pinecone_config=pinecone_config,
                namespace=namespace,
                resolved_company=resolved_company,
                namespace_prefix=pinecone_config.namespace_prefix,
                chunk_size=chunk_size,
                overlap=overlap,
            )

        return _RunnerDependencies(
            resolve_company=resolve_company_dependency,
            collect_sec_documents=collect_sec_documents_dependency,
            load_document_content=load_document_content_dependency,
            ingest_documents=ingest_documents_dependency,
            cleanup=stack.close,
        )
    except Exception:
        stack.close()
        raise


def _select_documents(
    documents: tuple[DocumentRecord, ...],
    filing_type: str,
    limit: int,
) -> tuple[DocumentRecord, ...]:
    normalized_filing_type = _normalize_filing_type(filing_type)
    eligible_documents = [
        document
        for document in documents
        if isinstance(document.filing_type, str) and document.filing_type.strip().upper() == normalized_filing_type
    ]
    eligible_documents.sort(
        key=lambda document: (
            document.filing_date or "",
            document.document_id,
            document.source_id,
        ),
        reverse=True,
    )
    return tuple(eligible_documents[:limit])


def _normalize_filing_type(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.strip().upper()


def _parse_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
    else:
        raise ValueError(f"{field_name} must be an integer.")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return parsed


def _parse_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
    else:
        raise ValueError(f"{field_name} must be an integer.")
    if parsed < 0:
        raise ValueError(f"{field_name} must be zero or positive.")
    return parsed


def _ensure_document_content(document: DocumentRecord, runtime_config: RuntimeConfig) -> DocumentRecord:
    if isinstance(document.content, str) and document.content.strip():
        return document
    if not isinstance(document.source_url, str) or not document.source_url.strip():
        raise ValueError("document source_url is required to load filing content.")

    headers = {
        "User-Agent": (runtime_config.sec_user_agent or "").strip(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if not headers["User-Agent"]:
        raise ValueError("SEC_USER_AGENT must be configured.")

    try:
        response = httpx.get(
            document.source_url,
            headers=headers,
            timeout=runtime_config.timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - network failure boundary
        raise RuntimeError("SEC filing content could not be loaded.") from exc

    content = _html_to_text(response.text)
    if not content.strip():
        raise RuntimeError("SEC filing content could not be extracted.")
    return replace(document, content=content)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self._ignored_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tags and self._ignored_tags[-1] == tag:
            self._ignored_tags.pop()

    def handle_data(self, data: str) -> None:
        if self._ignored_tags:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", parser.text()).strip()


def _build_summary(
    *,
    resolved_company: ResolvedCompany,
    filing_type: str,
    selected_document_count: int,
    ingestion_result: RAGIngestionResult,
) -> dict[str, object]:
    if ingestion_result.indexing_result is None:
        raise RuntimeError("ingestion summary could not be built.")

    indexing_result = ingestion_result.indexing_result
    return {
        "company_name": resolved_company.company_name,
        "ticker": resolved_company.ticker,
        "cik": resolved_company.cik,
        "filing_type": filing_type,
        "selected_document_count": selected_document_count,
        "chunk_count": ingestion_result.chunk_count,
        "prepared_vector_count": ingestion_result.prepared_vector_count,
        "indexed_vector_count": ingestion_result.indexed_vector_count,
        "accepted_vector_count": indexing_result.accepted_count,
        "namespace": indexing_result.namespace,
    }


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, SecTransportError):
        return "error: SEC transport failed after retry."
    if isinstance(exc, CompanyResolutionError):
        return "error: company resolution failed."
    if isinstance(exc, SecCollectionError):
        return "error: SEC collection failed."
    if isinstance(exc, ChunkEmbeddingError):
        return "error: embedding stage failed."
    if isinstance(exc, RuntimeError):
        return "error: SEC filing content could not be loaded."
    return "error: SEC ingestion adapter failed."


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
