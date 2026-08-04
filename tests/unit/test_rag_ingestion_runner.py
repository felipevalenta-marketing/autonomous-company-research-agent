"""Unit tests for the SEC-to-RAG ingestion adapter."""

from __future__ import annotations

import importlib
import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.clients.pinecone_dtos import PineconeUpsertResultDTO
from app.clients.sec_client import SecTransportError
from app.config.defaults import build_runtime_config
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.settings import Settings
from app.services.chunk_embedding_service import ChunkEmbeddingError
from app.services.embedding_service import EmbeddingServiceResult
from app.services.rag_ingestion_service import RAGIngestionResult
from app.services.vector_indexing_service import VectorIndexingResult


class RecordingResolveCompany:
    def __init__(self, result: ResolvedCompany | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def __call__(self, company_input: str) -> ResolvedCompany:
        self.calls.append(company_input)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("company resolution result was not configured.")
        return self.result


class RecordingCollectDocuments:
    def __init__(self, result: tuple[DocumentRecord, ...] | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[ResolvedCompany] = []

    def __call__(self, resolved_company: ResolvedCompany) -> tuple[DocumentRecord, ...]:
        self.calls.append(resolved_company)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("collected documents were not configured.")
        return self.result


class RecordingLoadContent:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[DocumentRecord] = []

    def __call__(self, document: DocumentRecord) -> DocumentRecord:
        self.calls.append(document)
        if self.error is not None:
            raise self.error
        if isinstance(document.content, str) and document.content.strip():
            return document
        return DocumentRecord(
            document_id=document.document_id,
            company_name=document.company_name,
            source_id=document.source_id,
            document_type=document.document_type,
            title=document.title,
            content=f"loaded content for {document.document_id}",
            storage_path=document.storage_path,
            source_url=document.source_url,
            filing_type=document.filing_type,
            filing_date=document.filing_date,
            fiscal_period=document.fiscal_period,
            extraction_status=document.extraction_status,
            chunk_count=document.chunk_count,
        )


class RecordingIngestDocuments:
    def __init__(self, result: RAGIngestionResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[tuple[DocumentRecord, ...], ResolvedCompany]] = []

    def __call__(self, documents: tuple[DocumentRecord, ...], resolved_company: ResolvedCompany) -> RAGIngestionResult:
        self.calls.append((documents, resolved_company))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("ingestion result was not configured.")
        return self.result


class RecordingClosableClient:
    instances: list["RecordingClosableClient"] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs
        self.close_count = 0
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.close_count += 1

    def query(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return SimpleNamespace()


class RecordingOpenAIEmbeddingsClient:
    instances: list["RecordingOpenAIEmbeddingsClient"] = []

    def __init__(self, runtime_config, *, base_url: str, default_model: str) -> None:
        self.runtime_config = runtime_config
        self.base_url = base_url
        self.default_model = default_model
        self.calls: list[tuple[tuple[str, ...], str, int | None]] = []
        self.__class__.instances.append(self)

    def create_embeddings(self, texts, model, dimensions=None):  # noqa: ANN001
        texts = tuple(texts)
        self.calls.append((texts, model, dimensions))

        class _Item:
            index = 0
            embedding = (0.1, 0.2, 0.3)

        class _Usage:
            prompt_tokens = 1
            total_tokens = 1

        return SimpleNamespace(model=model, data=[_Item()], usage=_Usage())

    def close(self) -> None:
        self.close_count = getattr(self, "close_count", 0) + 1


class RagIngestionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner_module = importlib.import_module("app.rag_ingestion_runner")
        self.factory_calls: list[tuple[Settings, object]] = []

    def _build_company(self) -> ResolvedCompany:
        return ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def _build_document(
        self,
        *,
        document_id: str,
        filing_type: str,
        filing_date: str,
        content: str | None = None,
    ) -> DocumentRecord:
        return DocumentRecord(
            document_id=document_id,
            company_name="Apple Inc.",
            source_id=f"source-{document_id}",
            document_type="sec_filing",
            title=f"{document_id} filing",
            content=content,
            source_url=f"https://example.com/{document_id}",
            filing_type=filing_type,
            filing_date=filing_date,
            fiscal_period="FY2024",
        )

    def _build_settings(self) -> Settings:
        return Settings(
            openai_api_key="demo",
            openai_base_url="https://api.openai.com/v1",
            openai_embedding_model="text-embedding-3-small",
            pinecone_api_key="demo",
            pinecone_index_name="index",
            pinecone_index_host="https://example.com",
            pinecone_namespace_prefix="company",
            pinecone_vector_dimension="3",
            pinecone_api_version=None,
            pinecone_max_upsert_batch_size="10",
            pinecone_max_query_top_k="5",
            tavily_api_key=None,
            news_api_key=None,
            alpha_vantage_api_key=None,
            sec_user_agent="Example App (dev@example.com)",
        )

    def _build_ingestion_result(self, namespace: str) -> RAGIngestionResult:
        acknowledgement = PineconeUpsertResultDTO(namespace=namespace, upserted_count=2)
        indexing_result = VectorIndexingResult(
            namespace=namespace,
            attempted_count=2,
            accepted_count=2,
            acknowledgements=(acknowledgement,),
        )
        return RAGIngestionResult(
            document_count=1,
            chunk_count=2,
            embedded_chunk_count=2,
            prepared_vector_count=2,
            indexed_vector_count=2,
            indexing_result=indexing_result,
        )

    def _build_dependencies_factory(
        self,
        *,
        resolver: RecordingResolveCompany,
        collector: RecordingCollectDocuments,
        loader: RecordingLoadContent,
        ingester: RecordingIngestDocuments,
    ):
        def factory(settings: Settings, args: object) -> SimpleNamespace:
            self.factory_calls.append((settings, args))
            return SimpleNamespace(
                resolve_company=resolver,
                collect_sec_documents=collector,
                load_document_content=loader,
                ingest_documents=ingester,
            )

        return factory

    def test_successful_execution_writes_single_json_object(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(
            result=(
                self._build_document(document_id="doc-old", filing_type="10-K", filing_date="2023-11-01"),
                self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01"),
                self._build_document(document_id="doc-q", filing_type="10-Q", filing_date="2024-08-01"),
            ),
        )
        loader = RecordingLoadContent()
        namespace = "company:cik:abc"
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result(namespace))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            payload,
            {
                "company_name": "Apple Inc.",
                "ticker": "AAPL",
                "cik": "0000320193",
                "filing_type": "10-K",
                "selected_document_count": 1,
                "chunk_count": 2,
                "prepared_vector_count": 2,
                "indexed_vector_count": 2,
                "accepted_vector_count": 2,
                "namespace": namespace,
            },
        )
        self.assertEqual(resolver.calls, ["Apple Inc."])
        self.assertEqual(len(collector.calls), 1)
        self.assertEqual(len(loader.calls), 1)
        self.assertEqual(loader.calls[0].document_id, "doc-new")
        self.assertEqual(len(ingester.calls), 1)
        selected_documents, resolved_company = ingester.calls[0]
        self.assertEqual(resolved_company.company_name, "Apple Inc.")
        self.assertEqual([document.document_id for document in selected_documents], ["doc-new"])
        self.assertEqual(selected_documents[0].content, "loaded content for doc-new")

    def test_sec_transport_failure_reports_safe_category(self) -> None:
        resolver = RecordingResolveCompany(error=SecTransportError("SEC request failed after retry."))
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error: SEC transport failed after retry.", stderr.getvalue())
        self.assertEqual(ingester.calls, [])

    def test_runner_closes_created_clients_on_success(self) -> None:
        resolve_calls: list[object] = []
        collect_calls: list[object] = []
        ingest_calls: list[object] = []

        def resolver(request, runtime_config, sec_client):  # noqa: ANN001
            resolve_calls.append((request, runtime_config, sec_client))
            return self._build_company()

        def collector(resolved_company, sec_client, runtime_config):  # noqa: ANN001
            collect_calls.append((resolved_company, sec_client, runtime_config))
            return (
                self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01", content="loaded content"),
            ), ()

        def ingester(
            documents,
            embedding_service,  # noqa: ANN001
            pinecone_client,  # noqa: ANN001
            pinecone_config,  # noqa: ANN001
            namespace,
            resolved_company,
            namespace_prefix,  # noqa: ANN001
            chunk_size,  # noqa: ANN001
            overlap,  # noqa: ANN001
        ):
            ingest_calls.append((documents, namespace, resolved_company))
            return self._build_ingestion_result(namespace)

        stdout = io.StringIO()
        stderr = io.StringIO()
        RecordingClosableClient.instances.clear()

        with patch.object(self.runner_module, "OpenAIEmbeddingsClient", RecordingClosableClient), patch.object(
            self.runner_module,
            "SecClient",
            RecordingClosableClient,
        ), patch.object(
            self.runner_module,
            "PineconeClient",
            RecordingClosableClient,
        ), patch.object(self.runner_module, "resolve_company", resolver), patch.object(
            self.runner_module,
            "collect_sec_documents",
            collector,
        ), patch.object(
            self.runner_module,
            "ingest_documents",
            ingester,
        ):
            exit_code = self.runner_module.main(
                ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
                settings_loader=lambda: self._build_settings(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(RecordingClosableClient.instances)
        self.assertTrue(all(client.close_count == 1 for client in RecordingClosableClient.instances))
        self.assertEqual(len(resolve_calls), 1)
        self.assertEqual(len(collect_calls), 1)
        self.assertEqual(len(ingest_calls), 1)

    def test_runner_closes_created_clients_on_failure(self) -> None:
        resolve_calls: list[object] = []
        collect_calls: list[object] = []
        ingest_calls: list[object] = []

        def resolver(request, runtime_config, sec_client):  # noqa: ANN001
            resolve_calls.append((request, runtime_config, sec_client))
            return self._build_company()

        def collector(resolved_company, sec_client, runtime_config):  # noqa: ANN001
            collect_calls.append((resolved_company, sec_client, runtime_config))
            return (
                self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01", content="loaded content"),
            ), ()

        def ingester(
            documents,
            embedding_service,  # noqa: ANN001
            pinecone_client,  # noqa: ANN001
            pinecone_config,  # noqa: ANN001
            namespace,
            resolved_company,
            namespace_prefix,  # noqa: ANN001
            chunk_size,  # noqa: ANN001
            overlap,  # noqa: ANN001
        ):
            ingest_calls.append((documents, namespace, resolved_company))
            raise ChunkEmbeddingError("boom")

        stdout = io.StringIO()
        stderr = io.StringIO()
        RecordingClosableClient.instances.clear()

        with patch.object(self.runner_module, "OpenAIEmbeddingsClient", RecordingClosableClient), patch.object(
            self.runner_module,
            "SecClient",
            RecordingClosableClient,
        ), patch.object(
            self.runner_module,
            "PineconeClient",
            RecordingClosableClient,
        ), patch.object(self.runner_module, "resolve_company", resolver), patch.object(
            self.runner_module,
            "collect_sec_documents",
            collector,
        ), patch.object(
            self.runner_module,
            "ingest_documents",
            ingester,
        ):
            exit_code = self.runner_module.main(
                ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
                settings_loader=lambda: self._build_settings(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(RecordingClosableClient.instances)
        self.assertTrue(all(client.close_count == 1 for client in RecordingClosableClient.instances))
        self.assertEqual(len(resolve_calls), 1)
        self.assertEqual(len(collect_calls), 1)
        self.assertEqual(len(ingest_calls), 1)

    def test_build_application_dependencies_uses_callable_embedding_boundary(self) -> None:
        captured = {}
        RecordingOpenAIEmbeddingsClient.instances.clear()

        def fake_ingest_documents(*args, **kwargs):  # noqa: ANN001
            captured["embedding_service"] = kwargs.get("embedding_service")
            embedding_result = kwargs["embedding_service"](("probe text",))
            captured["embedding_result"] = embedding_result
            captured["embedding_client"] = captured["embedding_service"].keywords["embedding_client"]
            return self._build_ingestion_result(kwargs["namespace"])

        with patch.object(self.runner_module, "OpenAIEmbeddingsClient", RecordingOpenAIEmbeddingsClient), patch.object(
            self.runner_module,
            "ingest_documents",
            fake_ingest_documents,
        ):
            dependencies = self.runner_module._build_application_dependencies(
                self._build_settings(),
                SimpleNamespace(company="Apple Inc.", filing_type="10-K", limit="1", chunk_size="1000", overlap="200"),
            )

            result = dependencies.ingest_documents(
                (
                    self._build_document(
                        document_id="doc-new",
                        filing_type="10-K",
                        filing_date="2024-11-01",
                        content="loaded content",
                    ),
                ),
                self._build_company(),
            )

        self.assertTrue(callable(captured["embedding_service"]))
        self.assertIs(captured["embedding_service"].func, self.runner_module.embed_texts)
        self.assertIsInstance(captured["embedding_result"], EmbeddingServiceResult)
        self.assertEqual(RecordingOpenAIEmbeddingsClient.instances[-1].calls, [(("probe text",), "text-embedding-3-small", None)])
        self.assertIs(captured["embedding_client"], RecordingOpenAIEmbeddingsClient.instances[-1])
        self.assertIsInstance(result, RAGIngestionResult)

    def test_blank_company_rejected_before_execution(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "   ", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--company must be a non-blank string.", stderr.getvalue())
        self.assertEqual(resolver.calls, [])
        self.assertEqual(collector.calls, [])
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_invalid_filing_type_rejected_before_execution(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "8-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--filing-type must be one of: 10-K, 10-Q.", stderr.getvalue())
        self.assertEqual(resolver.calls, [])
        self.assertEqual(collector.calls, [])
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_invalid_limit_rejected_before_execution(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "0"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--limit must be positive.", stderr.getvalue())
        self.assertEqual(resolver.calls, [])
        self.assertEqual(collector.calls, [])
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_limit_above_maximum_rejected_before_execution(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "4"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--limit must not exceed 3.", stderr.getvalue())
        self.assertEqual(resolver.calls, [])
        self.assertEqual(collector.calls, [])
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_company_resolution_failure_returns_nonzero(self) -> None:
        resolver = RecordingResolveCompany(error=RuntimeError("resolution failed"))
        collector = RecordingCollectDocuments(result=())
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())
        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(collector.calls, [])
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_empty_document_result_prevents_ingestion(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(
            result=(
                self._build_document(document_id="doc-q", filing_type="10-Q", filing_date="2024-08-01"),
            ),
        )
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(result=self._build_ingestion_result("company:cik:abc"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("no eligible SEC filings were found", stderr.getvalue())
        self.assertEqual(resolver.calls, ["Apple Inc."])
        self.assertEqual(collector.calls[0].company_name, "Apple Inc.")
        self.assertEqual(loader.calls, [])
        self.assertEqual(ingester.calls, [])

    def test_ingestion_failure_returns_nonzero(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(
            result=(
                self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01"),
            ),
        )
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(error=RuntimeError("ingestion failed"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())
        self.assertEqual(len(loader.calls), 1)
        self.assertEqual(len(ingester.calls), 1)

    def test_embedding_failure_reports_safe_category(self) -> None:
        resolver = RecordingResolveCompany(result=self._build_company())
        collector = RecordingCollectDocuments(
            result=(
                self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01"),
            ),
        )
        loader = RecordingLoadContent()
        ingester = RecordingIngestDocuments(error=ChunkEmbeddingError("chunk embedding failed."))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = self.runner_module.main(
            ["--company", "Apple Inc.", "--filing-type", "10-K", "--limit", "1"],
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=self._build_dependencies_factory(
                resolver=resolver,
                collector=collector,
                loader=loader,
                ingester=ingester,
            ),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error: embedding stage failed.", stderr.getvalue())
        self.assertEqual(len(loader.calls), 1)
        self.assertEqual(len(ingester.calls), 1)

    def test_ensure_document_content_repairs_utf8_bytes_with_wrong_charset(self) -> None:
        document = self._build_document(document_id="doc-new", filing_type="10-K", filing_date="2024-11-01", content=None)
        html = bytes(
            [
                0x3C,
                0x68,
                0x74,
                0x6D,
                0x6C,
                0x3E,
                0x3C,
                0x62,
                0x6F,
                0x64,
                0x79,
                0x3E,
                0x43,
                0x6F,
                0x6D,
                0x70,
                0x61,
                0x6E,
                0x79,
                0xE2,
                0x80,
                0x99,
                0x73,
                0x20,
                0x6D,
                0x61,
                0x6E,
                0x61,
                0x67,
                0x65,
                0x6D,
                0x65,
                0x6E,
                0x74,
                0x20,
                0xE2,
                0x80,
                0x94,
                0x20,
                0x61,
                0x6E,
                0x64,
                0x20,
                0x69,
                0x6E,
                0x74,
                0x65,
                0x72,
                0x65,
                0x73,
                0x74,
                0x20,
                0x72,
                0x61,
                0x74,
                0x65,
                0xE2,
                0x80,
                0x91,
                0x73,
                0x65,
                0x6E,
                0x73,
                0x69,
                0x74,
                0x69,
                0x76,
                0x65,
                0x20,
                0x63,
                0x6F,
                0x75,
                0x6E,
                0x74,
                0x65,
                0x72,
                0x70,
                0x61,
                0x72,
                0x74,
                0x69,
                0x65,
                0x73,
                0x2E,
                0x3C,
                0x2F,
                0x62,
                0x6F,
                0x64,
                0x79,
                0x3E,
                0x3C,
                0x2F,
                0x68,
                0x74,
                0x6D,
                0x6C,
                0x3E,
            ]
        )
        request = httpx.Request("GET", document.source_url)
        response = httpx.Response(200, request=request, content=html, headers={"Content-Type": "text/html; charset=iso-8859-1"})

        with patch.object(self.runner_module.httpx, "get", return_value=response):
            loaded = self.runner_module._ensure_document_content(document, build_runtime_config(self._build_settings()))

        self.assertIsNotNone(loaded.content)
        self.assertIn(chr(0x2019), loaded.content)
        self.assertIn(chr(0x2014), loaded.content)
        self.assertIn(chr(0x2011), loaded.content)
        self.assertNotIn("â", loaded.content)
        self.assertNotIn("?", loaded.content)

    def test_ensure_document_content_decodes_html_entities_and_preserves_ascii(self) -> None:
        document = self._build_document(document_id="doc-entities", filing_type="10-K", filing_date="2024-11-01", content=None)
        html = "<html><body>Apple&apos;s guidance &mdash; unchanged ASCII 123.</body></html>".encode("utf-8")
        request = httpx.Request("GET", document.source_url)
        response = httpx.Response(200, request=request, content=html, headers={"Content-Type": "text/html"})

        with patch.object(self.runner_module.httpx, "get", return_value=response):
            loaded = self.runner_module._ensure_document_content(document, build_runtime_config(self._build_settings()))

        self.assertEqual(loaded.content, "Apple's guidance — unchanged ASCII 123.")
        self.assertTrue(loaded.content.endswith("123."))
        self.assertIn("'", loaded.content)
        self.assertIn("—", loaded.content)

    def test_import_isolation(self) -> None:
        snapshot = dict(os.environ)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            module = importlib.reload(importlib.import_module("app.rag_ingestion_runner"))

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(dict(os.environ), snapshot)
        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(stripped.startswith("import openai"))
            self.assertFalse(stripped.startswith("from openai"))
            self.assertFalse(stripped.startswith("import langchain"))
            self.assertFalse(stripped.startswith("from langchain"))
            self.assertFalse(stripped.startswith("import pinecone"))
            self.assertFalse(stripped.startswith("from pinecone"))
            self.assertFalse(stripped.startswith("import fastapi"))
            self.assertFalse(stripped.startswith("from fastapi"))
            self.assertFalse(stripped.startswith("import flask"))
            self.assertFalse(stripped.startswith("from flask"))
            self.assertFalse(stripped.startswith("import django"))
            self.assertFalse(stripped.startswith("from django"))
        for pattern in (
            r"\bnewsapi\b",
            r"\btavily\b",
            r"\balpha_vantage\b",
            r"\bfastapi\b",
            r"\bflask\b",
            r"\bdjango\b",
            r"\bwebhook\b",
            r"\bn8n\b",
            r"\breact\b",
            r"\breport\b",
            r"\bprompt\b",
            r"\bmarkdown\b",
            r"\bpdf\b",
            r"\bexporter\b",
            r"\buuid\b",
            r"datetime\.now",
            r"\brandom\b",
            r"\bconcurrent\b",
            r"\bthread\b",
            r"\bqueue\b",
        ):
            self.assertIsNone(re.search(pattern, source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
