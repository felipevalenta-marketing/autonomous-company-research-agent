"""Deterministic orchestration for document ingestion into the RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.clients.pinecone_client import PineconeClientProtocol
from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.defaults import PineconeConfig
from app.models.chunks import ChunkRecord
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.services.chunk_embedding_service import (
    ChunkEmbeddingError,
    EmbeddedChunkRecord,
    embed_chunks,
)
from app.services.chunk_vector_indexing_service import (
    ChunkVectorIndexingError,
    index_chunk_vectors,
)
from app.services.chunk_vector_preparation_service import (
    ChunkVectorPreparationError,
    prepare_chunk_vectors,
)
from app.services.document_chunking_service import (
    DEFAULT_DOCUMENT_CHUNK_OVERLAP,
    DEFAULT_DOCUMENT_CHUNK_SIZE,
    DocumentChunkingError,
    chunk_document,
)
from app.services.embedding_service import EmbeddingClientProtocol
from app.services.vector_indexing_service import VectorIndexingError, VectorIndexingResult


class RAGIngestionError(Exception):
    """Base exception for RAG ingestion failures."""


class RAGIngestionInputError(RAGIngestionError):
    """Raised when RAG ingestion inputs are invalid."""


class RAGIngestionConsistencyError(RAGIngestionError):
    """Raised when stage outputs are inconsistent with the approved contracts."""


@dataclass(frozen=True, slots=True)
class RAGIngestionResult:
    """Immutable summary of a completed ingestion run.

    indexed_vector_count records the number of vectors handed to the indexing
    boundary; success vs. acceptance remains available on indexing_result.
    """

    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    prepared_vector_count: int
    indexed_vector_count: int
    indexing_result: VectorIndexingResult | None = None

    def __post_init__(self) -> None:
        counts = (
            self.document_count,
            self.chunk_count,
            self.embedded_chunk_count,
            self.prepared_vector_count,
            self.indexed_vector_count,
        )
        for value in counts:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("ingestion counts must be zero or positive integers.")

        if self.indexing_result is None:
            if any(count != 0 for count in counts):
                raise ValueError("empty ingestion results must not report non-zero counts.")
            return

        if not isinstance(self.indexing_result, VectorIndexingResult):
            raise ValueError("indexing_result must be a VectorIndexingResult instance.")
        if any(count == 0 for count in counts):
            raise ValueError("non-empty ingestion results must report positive counts.")
        if not (
            self.chunk_count == self.embedded_chunk_count == self.prepared_vector_count == self.indexed_vector_count
        ):
            raise ValueError("ingestion counts must remain consistent.")
        if self.indexed_vector_count != self.indexing_result.attempted_count:
            raise ValueError("indexed_vector_count must match the indexing result.")


class DocumentChunkingServiceProtocol(Protocol):
    """Callable boundary for deterministic document chunking."""

    def __call__(
        self,
        document: DocumentRecord,
        *,
        chunk_size: int,
        overlap: int,
    ) -> tuple[ChunkRecord, ...]:
        """Chunk a canonical document into immutable chunk records."""


class ChunkEmbeddingServiceOrchestratorProtocol(Protocol):
    """Callable boundary for deterministic chunk embedding orchestration."""

    def __call__(
        self,
        chunks: tuple[ChunkRecord, ...],
        embedding_service: EmbeddingClientProtocol,
    ) -> tuple[EmbeddedChunkRecord, ...]:
        """Embed a tuple of chunks into immutable embedded chunk records."""


class ChunkVectorPreparationServiceOrchestratorProtocol(Protocol):
    """Callable boundary for deterministic chunk vector preparation orchestration."""

    def __call__(
        self,
        embedded_chunks: tuple[EmbeddedChunkRecord, ...],
        *,
        resolved_company: ResolvedCompany | None = None,
        namespace_prefix: str | None = None,
    ) -> tuple[PineconeVectorRecordDTO, ...]:
        """Prepare Pinecone-ready vector records from embedded chunks."""


class ChunkVectorIndexingServiceOrchestratorProtocol(Protocol):
    """Callable boundary for deterministic chunk vector indexing orchestration."""

    def __call__(
        self,
        prepared_vectors: tuple[PineconeVectorRecordDTO, ...],
        pinecone_client: PineconeClientProtocol,
        namespace: str,
        pinecone_config: PineconeConfig,
        *,
        batch_size: int | None = None,
    ) -> VectorIndexingResult:
        """Index prepared vector records through the Pinecone boundary."""


def ingest_documents(
    documents: tuple[DocumentRecord, ...],
    *,
    embedding_service: EmbeddingClientProtocol,
    pinecone_client: PineconeClientProtocol,
    pinecone_config: PineconeConfig,
    namespace: str,
    resolved_company: ResolvedCompany | None = None,
    namespace_prefix: str | None = None,
    chunk_size: int = DEFAULT_DOCUMENT_CHUNK_SIZE,
    overlap: int = DEFAULT_DOCUMENT_CHUNK_OVERLAP,
    batch_size: int | None = None,
    document_chunking_service: DocumentChunkingServiceProtocol = chunk_document,
    chunk_embedding_service: ChunkEmbeddingServiceOrchestratorProtocol = embed_chunks,
    chunk_vector_preparation_service: ChunkVectorPreparationServiceOrchestratorProtocol = prepare_chunk_vectors,
    chunk_vector_indexing_service: ChunkVectorIndexingServiceOrchestratorProtocol = index_chunk_vectors,
) -> RAGIngestionResult:
    """Run the approved ingestion stages in deterministic document order."""

    normalized_documents = _normalize_documents(documents)
    if not normalized_documents:
        return _build_empty_result()

    all_chunks: list[ChunkRecord] = []
    all_embedded_chunks: list[EmbeddedChunkRecord] = []
    all_prepared_vectors: list[PineconeVectorRecordDTO] = []
    seen_chunk_ids: set[str] = set()
    seen_record_ids: set[str] = set()

    for document in normalized_documents:
        chunks = _call_chunking_stage(
            document,
            chunk_size=chunk_size,
            overlap=overlap,
            document_chunking_service=document_chunking_service,
        )
        normalized_chunks = _normalize_chunk_batch(document, chunks, seen_chunk_ids)
        all_chunks.extend(normalized_chunks)

        embedded_chunks = _call_embedding_stage(
            normalized_chunks,
            embedding_service=embedding_service,
            chunk_embedding_service=chunk_embedding_service,
        )
        normalized_embedded_chunks = _normalize_embedded_chunk_batch(normalized_chunks, embedded_chunks)
        all_embedded_chunks.extend(normalized_embedded_chunks)

        prepared_vectors = _call_preparation_stage(
            normalized_embedded_chunks,
            resolved_company=resolved_company,
            namespace_prefix=namespace_prefix,
            chunk_vector_preparation_service=chunk_vector_preparation_service,
        )
        normalized_prepared_vectors = _normalize_prepared_vector_batch(
            normalized_embedded_chunks,
            prepared_vectors,
            seen_record_ids,
        )
        all_prepared_vectors.extend(normalized_prepared_vectors)

    indexing_result = _call_indexing_stage(
        tuple(all_prepared_vectors),
        pinecone_client=pinecone_client,
        namespace=namespace,
        pinecone_config=pinecone_config,
        batch_size=batch_size,
        chunk_vector_indexing_service=chunk_vector_indexing_service,
    )
    _validate_indexing_result(indexing_result, len(all_prepared_vectors))

    if not (
        len(all_chunks) == len(all_embedded_chunks) == len(all_prepared_vectors) == indexing_result.attempted_count
    ):
        raise RAGIngestionConsistencyError("ingestion stage counts must remain consistent.")

    return RAGIngestionResult(
        document_count=len(normalized_documents),
        chunk_count=len(all_chunks),
        embedded_chunk_count=len(all_embedded_chunks),
        prepared_vector_count=len(all_prepared_vectors),
        indexed_vector_count=indexing_result.attempted_count,
        indexing_result=indexing_result,
    )


def _normalize_documents(documents: object) -> tuple[DocumentRecord, ...]:
    if not isinstance(documents, tuple):
        raise RAGIngestionInputError("documents must be an immutable tuple of DocumentRecord instances.")
    if not documents:
        return ()

    normalized: list[DocumentRecord] = []
    seen_document_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, DocumentRecord):
            raise RAGIngestionInputError("documents must contain DocumentRecord instances.")
        if document.document_id in seen_document_ids:
            raise RAGIngestionInputError("document_id values must be unique.")
        seen_document_ids.add(document.document_id)
        normalized.append(document)
    return tuple(normalized)


def _call_chunking_stage(
    document: DocumentRecord,
    *,
    chunk_size: int,
    overlap: int,
    document_chunking_service: DocumentChunkingServiceProtocol,
) -> tuple[ChunkRecord, ...]:
    try:
        return document_chunking_service(document, chunk_size=chunk_size, overlap=overlap)
    except DocumentChunkingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGIngestionError("document chunking failed.") from exc


def _call_embedding_stage(
    chunks: tuple[ChunkRecord, ...],
    *,
    embedding_service: EmbeddingClientProtocol,
    chunk_embedding_service: ChunkEmbeddingServiceOrchestratorProtocol,
) -> tuple[EmbeddedChunkRecord, ...]:
    try:
        return chunk_embedding_service(chunks, embedding_service)
    except ChunkEmbeddingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGIngestionError("chunk embedding failed.") from exc


def _call_preparation_stage(
    embedded_chunks: tuple[EmbeddedChunkRecord, ...],
    *,
    resolved_company: ResolvedCompany | None,
    namespace_prefix: str | None,
    chunk_vector_preparation_service: ChunkVectorPreparationServiceOrchestratorProtocol,
) -> tuple[PineconeVectorRecordDTO, ...]:
    try:
        return chunk_vector_preparation_service(
            embedded_chunks,
            resolved_company=resolved_company,
            namespace_prefix=namespace_prefix,
        )
    except ChunkVectorPreparationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGIngestionError("chunk vector preparation failed.") from exc


def _call_indexing_stage(
    prepared_vectors: tuple[PineconeVectorRecordDTO, ...],
    *,
    pinecone_client: PineconeClientProtocol,
    namespace: str,
    pinecone_config: PineconeConfig,
    batch_size: int | None,
    chunk_vector_indexing_service: ChunkVectorIndexingServiceOrchestratorProtocol,
) -> VectorIndexingResult:
    try:
        return chunk_vector_indexing_service(
            prepared_vectors,
            pinecone_client,
            namespace,
            pinecone_config,
            batch_size=batch_size,
        )
    except (ChunkVectorIndexingError, VectorIndexingError):
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RAGIngestionError("chunk vector indexing failed.") from exc


def _normalize_chunk_batch(
    document: DocumentRecord,
    chunks: object,
    seen_chunk_ids: set[str],
) -> tuple[ChunkRecord, ...]:
    if not isinstance(chunks, tuple):
        raise RAGIngestionConsistencyError("chunking must return a tuple of ChunkRecord instances.")
    if not chunks:
        raise RAGIngestionConsistencyError("documents must produce at least one chunk.")

    normalized: list[ChunkRecord] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, ChunkRecord):
            raise RAGIngestionConsistencyError("chunking must return ChunkRecord instances.")
        if chunk.document_id != document.document_id:
            raise RAGIngestionConsistencyError("chunking must preserve the document identity.")
        if chunk.source_id != document.source_id:
            raise RAGIngestionConsistencyError("chunking must preserve the source identity.")
        if chunk.chunk_index != index:
            raise RAGIngestionConsistencyError("chunking must preserve chunk ordering.")
        if chunk.chunk_id in seen_chunk_ids:
            raise RAGIngestionConsistencyError("chunk_id values must be unique.")
        seen_chunk_ids.add(chunk.chunk_id)
        normalized.append(chunk)
    return tuple(normalized)


def _normalize_embedded_chunk_batch(
    chunks: tuple[ChunkRecord, ...],
    embedded_chunks: object,
) -> tuple[EmbeddedChunkRecord, ...]:
    if not isinstance(embedded_chunks, tuple):
        raise RAGIngestionConsistencyError("embedding must return a tuple of EmbeddedChunkRecord instances.")
    if len(embedded_chunks) != len(chunks):
        raise RAGIngestionConsistencyError("embedding output must match the chunk count.")

    normalized: list[EmbeddedChunkRecord] = []
    seen_indexes: set[int] = set()
    for index, (chunk, embedded_chunk) in enumerate(zip(chunks, embedded_chunks, strict=True)):
        if not isinstance(embedded_chunk, EmbeddedChunkRecord):
            raise RAGIngestionConsistencyError("embedding must return EmbeddedChunkRecord instances.")
        if embedded_chunk.chunk != chunk:
            raise RAGIngestionConsistencyError("embedded chunks must preserve chunk lineage.")
        if embedded_chunk.embedding.input_index != index:
            raise RAGIngestionConsistencyError("embedded chunks must preserve the input ordering.")
        if embedded_chunk.embedding.input_index in seen_indexes:
            raise RAGIngestionConsistencyError("embedding input indexes must be unique.")
        seen_indexes.add(embedded_chunk.embedding.input_index)
        normalized.append(embedded_chunk)
    return tuple(normalized)


def _normalize_prepared_vector_batch(
    embedded_chunks: tuple[EmbeddedChunkRecord, ...],
    prepared_vectors: object,
    seen_record_ids: set[str],
) -> tuple[PineconeVectorRecordDTO, ...]:
    if not isinstance(prepared_vectors, tuple):
        raise RAGIngestionConsistencyError("vector preparation must return a tuple of PineconeVectorRecordDTO instances.")
    if len(prepared_vectors) != len(embedded_chunks):
        raise RAGIngestionConsistencyError("prepared vector output must match the embedded chunk count.")

    normalized: list[PineconeVectorRecordDTO] = []
    for embedded_chunk, prepared_vector in zip(embedded_chunks, prepared_vectors, strict=True):
        if not isinstance(prepared_vector, PineconeVectorRecordDTO):
            raise RAGIngestionConsistencyError("vector preparation must return PineconeVectorRecordDTO instances.")
        if prepared_vector.record_id in seen_record_ids:
            raise RAGIngestionConsistencyError("prepared vector record IDs must be unique.")
        seen_record_ids.add(prepared_vector.record_id)
        if prepared_vector.values != embedded_chunk.embedding.vector:
            raise RAGIngestionConsistencyError("prepared vectors must preserve the embedding values.")
        metadata = prepared_vector.metadata
        if metadata.get("chunk_id") != embedded_chunk.chunk.chunk_id:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve chunk identity.")
        if metadata.get("document_id") != embedded_chunk.chunk.document_id:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve document identity.")
        if metadata.get("source_id") != embedded_chunk.chunk.source_id:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve source identity.")
        if metadata.get("company_name") != embedded_chunk.chunk.company_name:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve company identity.")
        if metadata.get("text_id") != embedded_chunk.chunk.text:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve chunk text.")
        if metadata.get("content_checksum") != embedded_chunk.chunk.content_checksum:
            raise RAGIngestionConsistencyError("prepared vector metadata must preserve the chunk checksum.")
        normalized.append(prepared_vector)
    return tuple(normalized)


def _validate_indexing_result(result: VectorIndexingResult, expected_count: int) -> None:
    if not isinstance(result, VectorIndexingResult):
        raise RAGIngestionConsistencyError("vector indexing must return a VectorIndexingResult instance.")
    if result.attempted_count != expected_count:
        raise RAGIngestionConsistencyError("indexing attempted counts must match the prepared vector count.")
    if result.accepted_count < 0 or result.accepted_count > result.attempted_count:
        raise RAGIngestionConsistencyError("indexing accepted counts must remain bounded.")


def _build_empty_result() -> RAGIngestionResult:
    return RAGIngestionResult(
        document_count=0,
        chunk_count=0,
        embedded_chunk_count=0,
        prepared_vector_count=0,
        indexed_vector_count=0,
        indexing_result=None,
    )
