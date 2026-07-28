"""Unit tests for RAG ingestion orchestration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from app.clients.pinecone_dtos import PineconeUpsertResultDTO, PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.models.chunks import ChunkRecord
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.services.chunk_embedding_service import ChunkEmbeddingError, EmbeddedChunkRecord
from app.services.chunk_vector_indexing_service import ChunkVectorIndexingError
from app.services.chunk_vector_preparation_service import ChunkVectorPreparationError
from app.services.embedding_service import EmbeddingRecord
from app.services.rag_ingestion_service import (
    RAGIngestionConsistencyError,
    RAGIngestionInputError,
    RAGIngestionResult,
    ingest_documents,
)
from app.services.vector_indexing_service import VectorIndexingResult
from app.utils.hashing import sha256_text


def _build_document(
    *,
    document_id: str,
    content: str,
    company_name: str = "Example Corp",
    source_id: str = "source-1",
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        company_name=company_name,
        source_id=source_id,
        document_type="10-K",
        title=f"{document_id} filing",
        content=content,
        storage_path=None,
        source_url="https://example.com/doc",
        filing_type="10-K",
        filing_date="2024-01-01",
        fiscal_period="FY2024",
    )


def _build_chunk(
    document: DocumentRecord,
    *,
    chunk_id: str | None = None,
    chunk_index: int,
    text: str,
    source_url: str | None = None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id or sha256_text(f"{document.document_id}|{document.source_id}|{chunk_index}|{text}"),
        document_id=document.document_id,
        source_id=document.source_id,
        company_name=document.company_name,
        chunk_index=chunk_index,
        text=text,
        start_offset=0,
        end_offset=len(text),
        content_checksum=sha256_text(text),
        document_type=document.document_type,
        source_url=source_url if source_url is not None else document.source_url,
        filing_type=document.filing_type,
        filing_date=document.filing_date,
        fiscal_period=document.fiscal_period,
    )


def _build_embedding(chunk: ChunkRecord) -> EmbeddingRecord:
    return EmbeddingRecord(
        input_index=chunk.chunk_index,
        input_checksum=sha256_text(chunk.text),
        model="text-embedding-3-small",
        vector_dimension=3,
        vector=(float(chunk.chunk_index + 1), float(chunk.chunk_index + 2), float(chunk.chunk_index + 3)),
    )


def _build_embedded_chunk(chunk: ChunkRecord) -> EmbeddedChunkRecord:
    return EmbeddedChunkRecord(chunk=chunk, embedding=_build_embedding(chunk))


def _build_prepared_vector(embedded_chunk: EmbeddedChunkRecord) -> PineconeVectorRecordDTO:
    chunk = embedded_chunk.chunk
    return PineconeVectorRecordDTO(
        record_id=chunk.chunk_id,
        values=embedded_chunk.embedding.vector,
        metadata={
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source_id": chunk.source_id,
            "company_name": chunk.company_name,
            "text_id": chunk.text,
            "content_checksum": chunk.content_checksum,
            "filing_form": chunk.document_type,
            "source_url": chunk.source_url,
            "filing_date": chunk.filing_date,
        },
    )


def _build_indexing_result(namespace: str, prepared_vectors: tuple[PineconeVectorRecordDTO, ...]) -> VectorIndexingResult:
    return VectorIndexingResult(
        namespace=namespace,
        attempted_count=len(prepared_vectors),
        accepted_count=len(prepared_vectors),
        acknowledgements=(PineconeUpsertResultDTO(namespace=namespace, upserted_count=len(prepared_vectors)),),
    )


class FakeDocumentChunkingService:
    def __init__(self, chunks_by_document_id: dict[str, tuple[ChunkRecord, ...]], calls: list[str], exc: Exception | None = None) -> None:
        self.chunks_by_document_id = chunks_by_document_id
        self.calls = calls
        self.exc = exc

    def __call__(self, document: DocumentRecord, *, chunk_size: int, overlap: int) -> tuple[ChunkRecord, ...]:
        self.calls.append(f"chunk:{document.document_id}")
        if self.exc is not None:
            raise self.exc
        return self.chunks_by_document_id[document.document_id]


class FakeChunkEmbeddingService:
    def __init__(self, calls: list[str], exc: Exception | None = None) -> None:
        self.calls = calls
        self.exc = exc
        self.received_embedding_services: list[object] = []

    def __call__(self, chunks: tuple[ChunkRecord, ...], embedding_service: object) -> tuple[EmbeddedChunkRecord, ...]:
        document_id = chunks[0].document_id if chunks else "empty"
        self.calls.append(f"embed:{document_id}")
        self.received_embedding_services.append(embedding_service)
        if self.exc is not None:
            raise self.exc
        return tuple(_build_embedded_chunk(chunk) for chunk in chunks)


class FakeChunkVectorPreparationService:
    def __init__(self, calls: list[str], exc: Exception | None = None) -> None:
        self.calls = calls
        self.exc = exc
        self.received_arguments: list[tuple[ResolvedCompany | None, str | None]] = []

    def __call__(
        self,
        embedded_chunks: tuple[EmbeddedChunkRecord, ...],
        *,
        resolved_company: ResolvedCompany | None = None,
        namespace_prefix: str | None = None,
    ) -> tuple[PineconeVectorRecordDTO, ...]:
        document_id = embedded_chunks[0].chunk.document_id if embedded_chunks else "empty"
        self.calls.append(f"prep:{document_id}")
        self.received_arguments.append((resolved_company, namespace_prefix))
        if self.exc is not None:
            raise self.exc
        return tuple(_build_prepared_vector(embedded_chunk) for embedded_chunk in embedded_chunks)


class FakeChunkVectorIndexingService:
    def __init__(self, calls: list[str], exc: Exception | None = None, result_override: object | None = None) -> None:
        self.calls = calls
        self.exc = exc
        self.result_override = result_override
        self.received_arguments: list[tuple[tuple[PineconeVectorRecordDTO, ...], object, str, PineconeConfig, int | None]] = []

    def __call__(
        self,
        prepared_vectors: tuple[PineconeVectorRecordDTO, ...],
        pinecone_client,  # noqa: ANN001
        namespace: str,
        pinecone_config: PineconeConfig,
        *,
        batch_size: int | None = None,
    ) -> object:
        document_id = prepared_vectors[0].metadata["document_id"] if prepared_vectors else "empty"
        self.calls.append(f"index:{document_id}")
        self.received_arguments.append((prepared_vectors, pinecone_client, namespace, pinecone_config, batch_size))
        if self.exc is not None:
            raise self.exc
        if self.result_override is not None:
            return self.result_override
        return _build_indexing_result(namespace, prepared_vectors)


class RagIngestionServiceTests(unittest.TestCase):
    def test_valid_documents_run_each_stage_in_order_and_preserve_counts(self) -> None:
        document_1 = _build_document(document_id="doc-1", content="alpha beta")
        document_2 = _build_document(document_id="doc-2", content="gamma delta")
        chunks_by_document = {
            "doc-1": (_build_chunk(document_1, chunk_index=0, text="alpha beta"),),
            "doc-2": (
                _build_chunk(document_2, chunk_index=0, text="gamma"),
                _build_chunk(document_2, chunk_index=1, text="delta"),
            ),
        }
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(chunks_by_document, call_log)
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log)
        embedding_service = object()
        pinecone_client = object()
        pinecone_config = PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=3,
            api_version="2024-07",
            max_upsert_batch_size=2,
            max_query_top_k=10,
        )
        resolved_company = ResolvedCompany(company_name="Example Corp", ticker="EXM", cik="0000123456")

        result = ingest_documents(
            (document_1, document_2),
            embedding_service=embedding_service,
            pinecone_client=pinecone_client,
            pinecone_config=pinecone_config,
            namespace="company:cik:abc",
            resolved_company=resolved_company,
            namespace_prefix="company",
            chunk_size=128,
            overlap=16,
            batch_size=1,
            document_chunking_service=chunking,
            chunk_embedding_service=embedding,
            chunk_vector_preparation_service=preparation,
            chunk_vector_indexing_service=indexing,
        )

        self.assertEqual(
            call_log,
            [
                "chunk:doc-1",
                "embed:doc-1",
                "prep:doc-1",
                "chunk:doc-2",
                "embed:doc-2",
                "prep:doc-2",
                "index:doc-1",
            ],
        )
        self.assertEqual(result.document_count, 2)
        self.assertEqual(result.chunk_count, 3)
        self.assertEqual(result.embedded_chunk_count, 3)
        self.assertEqual(result.prepared_vector_count, 3)
        self.assertEqual(result.indexed_vector_count, 3)
        self.assertIsInstance(result.indexing_result, VectorIndexingResult)
        self.assertEqual(result.indexing_result.namespace, "company:cik:abc")
        self.assertEqual(result.indexing_result.attempted_count, 3)
        self.assertEqual(result.indexing_result.accepted_count, 3)
        self.assertEqual(len(result.indexing_result.acknowledgements), 1)
        self.assertIs(embedding.received_embedding_services[0], embedding_service)
        self.assertIs(preparation.received_arguments[0][0], resolved_company)
        self.assertEqual(preparation.received_arguments[0][1], "company")
        self.assertEqual(len(indexing.received_arguments), 1)
        self.assertEqual(indexing.received_arguments[0][1], pinecone_client)
        self.assertEqual(indexing.received_arguments[0][2], "company:cik:abc")
        self.assertIs(indexing.received_arguments[0][3], pinecone_config)
        self.assertEqual(indexing.received_arguments[0][4], 1)
        with self.assertRaises(FrozenInstanceError):
            result.document_count = 99  # type: ignore[misc]

    def test_indexing_acceptance_is_preserved_separately_from_attempted_count(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        chunks_by_document = {
            "doc-1": (_build_chunk(document, chunk_index=0, text="alpha beta"),),
        }
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(chunks_by_document, call_log)
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        namespace = "company:cik:abc"
        partial_result = VectorIndexingResult(
            namespace=namespace,
            attempted_count=1,
            accepted_count=0,
            acknowledgements=(),
        )
        indexing = FakeChunkVectorIndexingService(call_log, result_override=partial_result)

        result = ingest_documents(
            (document,),
            embedding_service=object(),
            pinecone_client=object(),
            pinecone_config=self._build_config(),
            namespace=namespace,
            document_chunking_service=chunking,
            chunk_embedding_service=embedding,
            chunk_vector_preparation_service=preparation,
            chunk_vector_indexing_service=indexing,
        )

        self.assertEqual(result.indexed_vector_count, 1)
        self.assertEqual(result.indexing_result.attempted_count, 1)
        self.assertEqual(result.indexing_result.accepted_count, 0)
        self.assertEqual(len(result.indexing_result.acknowledgements), 0)

    def test_empty_tuple_returns_empty_no_op_result_without_stage_calls(self) -> None:
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService({}, call_log)
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log)
        pinecone_config = PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=3,
            api_version="2024-07",
            max_upsert_batch_size=2,
            max_query_top_k=10,
        )

        result = ingest_documents(
            (),
            embedding_service=object(),
            pinecone_client=object(),
            pinecone_config=pinecone_config,
            namespace="   ",
            document_chunking_service=chunking,
            chunk_embedding_service=embedding,
            chunk_vector_preparation_service=preparation,
            chunk_vector_indexing_service=indexing,
        )

        self.assertEqual(result.document_count, 0)
        self.assertEqual(result.chunk_count, 0)
        self.assertEqual(result.embedded_chunk_count, 0)
        self.assertEqual(result.prepared_vector_count, 0)
        self.assertEqual(result.indexed_vector_count, 0)
        self.assertIsNone(result.indexing_result)
        self.assertEqual(call_log, [])

    def test_wrong_collection_type_rejected(self) -> None:
        with self.assertRaises(RAGIngestionInputError):
            ingest_documents(  # type: ignore[arg-type]
                [
                    _build_document(document_id="doc-1", content="alpha beta"),
                ],
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
            )

    def test_invalid_element_rejected(self) -> None:
        with self.assertRaises(RAGIngestionInputError):
            ingest_documents(  # type: ignore[arg-type]
                (_build_document(document_id="doc-1", content="alpha beta"), object()),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
            )

    def test_duplicate_document_id_rejected(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        duplicate = _build_document(document_id="doc-1", content="gamma delta", source_id="source-2")

        with self.assertRaises(RAGIngestionInputError):
            ingest_documents(
                (document, duplicate),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
            )

    def test_duplicate_chunk_id_across_documents_is_rejected(self) -> None:
        document_1 = _build_document(document_id="doc-1", content="alpha beta")
        document_2 = _build_document(document_id="doc-2", content="gamma delta")
        shared_chunk_id = "shared-chunk-id"
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {
                "doc-1": (
                    _build_chunk(document_1, chunk_id=shared_chunk_id, chunk_index=0, text="alpha beta"),
                ),
                "doc-2": (
                    _build_chunk(document_2, chunk_id=shared_chunk_id, chunk_index=0, text="gamma delta"),
                ),
            },
            call_log,
        )

        with self.assertRaises(RAGIngestionConsistencyError):
            ingest_documents(
                (document_1, document_2),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
                document_chunking_service=chunking,
                chunk_embedding_service=FakeChunkEmbeddingService(call_log),
                chunk_vector_preparation_service=FakeChunkVectorPreparationService(call_log),
                chunk_vector_indexing_service=FakeChunkVectorIndexingService(call_log),
            )

    def test_input_tuple_remains_unchanged(self) -> None:
        documents = (
            _build_document(document_id="doc-1", content="alpha beta"),
        )
        snapshot = documents

        ingest_documents(
            documents,
            embedding_service=object(),
            pinecone_client=object(),
            pinecone_config=self._build_config(),
            namespace="company:cik:abc",
            document_chunking_service=FakeDocumentChunkingService(
                {"doc-1": (_build_chunk(documents[0], chunk_index=0, text="alpha beta"),)},
                [],
            ),
            chunk_embedding_service=FakeChunkEmbeddingService([]),
            chunk_vector_preparation_service=FakeChunkVectorPreparationService([]),
            chunk_vector_indexing_service=FakeChunkVectorIndexingService([]),
        )

        self.assertIs(documents, snapshot)
        self.assertEqual(documents[0].document_id, "doc-1")

    def test_embedding_failure_propagates_without_later_stage_calls(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {"doc-1": (_build_chunk(document, chunk_index=0, text="alpha beta"),)},
            call_log,
        )
        embedding = FakeChunkEmbeddingService(call_log, exc=ChunkEmbeddingError("boom"))
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log)

        with self.assertRaises(ChunkEmbeddingError):
            ingest_documents(
                (document,),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
                document_chunking_service=chunking,
                chunk_embedding_service=embedding,
                chunk_vector_preparation_service=preparation,
                chunk_vector_indexing_service=indexing,
            )

        self.assertEqual(call_log, ["chunk:doc-1", "embed:doc-1"])

    def test_preparation_failure_propagates_without_indexing(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {"doc-1": (_build_chunk(document, chunk_index=0, text="alpha beta"),)},
            call_log,
        )
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log, exc=ChunkVectorPreparationError("boom"))
        indexing = FakeChunkVectorIndexingService(call_log)

        with self.assertRaises(ChunkVectorPreparationError):
            ingest_documents(
                (document,),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
                document_chunking_service=chunking,
                chunk_embedding_service=embedding,
                chunk_vector_preparation_service=preparation,
                chunk_vector_indexing_service=indexing,
            )

        self.assertEqual(call_log, ["chunk:doc-1", "embed:doc-1", "prep:doc-1"])

    def test_indexing_failure_propagates_without_partial_success(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {"doc-1": (_build_chunk(document, chunk_index=0, text="alpha beta"),)},
            call_log,
        )
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log, exc=ChunkVectorIndexingError("boom"))

        with self.assertRaises(ChunkVectorIndexingError):
            ingest_documents(
                (document,),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
                document_chunking_service=chunking,
                chunk_embedding_service=embedding,
                chunk_vector_preparation_service=preparation,
                chunk_vector_indexing_service=indexing,
            )

        self.assertEqual(call_log, ["chunk:doc-1", "embed:doc-1", "prep:doc-1", "index:doc-1"])

    def test_malformed_stage_output_is_rejected_before_success(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {"doc-1": (_build_chunk(document, chunk_index=0, text="alpha beta"),)},
            call_log,
        )

        class BadEmbeddingService(FakeChunkEmbeddingService):
            def __call__(self, chunks, embedding_service):  # noqa: ANN001
                super().__call__(chunks, embedding_service)
                return ()

        embedding = BadEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log)

        with self.assertRaises(RAGIngestionConsistencyError):
            ingest_documents(
                (document,),
                embedding_service=object(),
                pinecone_client=object(),
                pinecone_config=self._build_config(),
                namespace="company:cik:abc",
                document_chunking_service=chunking,
                chunk_embedding_service=embedding,
                chunk_vector_preparation_service=preparation,
                chunk_vector_indexing_service=indexing,
            )

        self.assertEqual(call_log, ["chunk:doc-1", "embed:doc-1"])

    def test_repeated_calls_are_deterministic(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        documents = (document,)
        first = self._run_ingestion(documents)
        second = self._run_ingestion(documents)

        self.assertEqual(first, second)

    def test_no_hidden_accumulation(self) -> None:
        document = _build_document(document_id="doc-1", content="alpha beta")
        documents = (document,)
        first = self._run_ingestion(documents)
        second = self._run_ingestion(documents)

        self.assertEqual(first, second)

    def test_no_forbidden_imports_in_source(self) -> None:
        with open("app/services/rag_ingestion_service.py", encoding="utf-8") as handle:
            source = handle.read()

        for forbidden in (
            "from openai",
            "import openai",
            "from pinecone",
            "import pinecone",
            "Pinecone(",
            "Index(",
            "PineconeClient(",
            "from langgraph",
            "import langgraph",
            "SEC",
            "AlphaVantage",
            "NewsAPI",
            "Tavily",
            "app.models.state",
            "app.rag",
            "from report",
            "import report",
            "from prompts",
            "import prompts",
            "from exporters",
            "import exporters",
            "from n8n",
            "import n8n",
            "os.environ",
            "os.getenv",
        ):
            self.assertNotIn(forbidden, source)

    def _build_config(self) -> PineconeConfig:
        return PineconeConfig(
            api_key="pinecone-key",
            index_host="https://example-index.svc.pinecone.io",
            namespace_prefix="company",
            vector_dimension=3,
            api_version="2024-07",
            max_upsert_batch_size=2,
            max_query_top_k=10,
        )

    def _run_ingestion(self, documents: tuple[DocumentRecord, ...]) -> RAGIngestionResult:
        call_log: list[str] = []
        chunking = FakeDocumentChunkingService(
            {
                "doc-1": (_build_chunk(documents[0], chunk_index=0, text="alpha beta"),),
            },
            call_log,
        )
        embedding = FakeChunkEmbeddingService(call_log)
        preparation = FakeChunkVectorPreparationService(call_log)
        indexing = FakeChunkVectorIndexingService(call_log)

        return ingest_documents(
            documents,
            embedding_service=object(),
            pinecone_client=object(),
            pinecone_config=self._build_config(),
            namespace="company:cik:abc",
            resolved_company=ResolvedCompany(company_name="Example Corp", ticker="EXM", cik="0000123456"),
            namespace_prefix="company",
            document_chunking_service=chunking,
            chunk_embedding_service=embedding,
            chunk_vector_preparation_service=preparation,
            chunk_vector_indexing_service=indexing,
        )
