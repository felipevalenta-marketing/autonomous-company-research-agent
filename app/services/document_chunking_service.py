"""Deterministic fixed-size document chunking."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.chunks import ChunkRecord
from app.models.documents import DocumentRecord
from app.utils.hashing import sha256_text

DEFAULT_DOCUMENT_CHUNK_SIZE = 1000
DEFAULT_DOCUMENT_CHUNK_OVERLAP = 100


class DocumentChunkingError(Exception):
    """Base exception for document chunking failures."""


class DocumentChunkingInputError(DocumentChunkingError):
    """Raised when chunking inputs are invalid."""


class ChunkConfigurationError(DocumentChunkingError):
    """Raised when chunk configuration is invalid."""


class ChunkValidationError(DocumentChunkingError):
    """Raised when a generated chunk fails validation."""


@dataclass(frozen=True, slots=True)
class _ChunkSpan:
    start_offset: int
    end_offset: int
    chunk_index: int
    text: str
    content_checksum: str
    chunk_id: str


def chunk_document(
    document: DocumentRecord,
    *,
    chunk_size: int = DEFAULT_DOCUMENT_CHUNK_SIZE,
    overlap: int = DEFAULT_DOCUMENT_CHUNK_OVERLAP,
) -> tuple[ChunkRecord, ...]:
    """Split a canonical document into deterministic fixed-size chunks."""

    _require_document(document)
    size = _require_positive_int(chunk_size, "chunk_size")
    overlap_size = _require_nonnegative_int(overlap, "overlap")
    if overlap_size >= size:
        raise ChunkConfigurationError("overlap must be smaller than chunk_size.")

    content = document.content
    if not isinstance(content, str):
        raise DocumentChunkingInputError("document content must be a string.")
    if not content.strip():
        raise DocumentChunkingInputError("document content must not be empty.")

    chunks: list[ChunkRecord] = []
    text_length = len(content)
    start_offset = 0
    chunk_index = 0

    while start_offset < text_length:
        end_offset = min(start_offset + size, text_length)
        chunk_text = content[start_offset:end_offset]
        if not chunk_text:
            raise ChunkValidationError("generated chunk text must not be empty.")

        span = _build_chunk_span(
            document=document,
            chunk_index=chunk_index,
            start_offset=start_offset,
            end_offset=end_offset,
            chunk_text=chunk_text,
        )
        chunks.append(
            ChunkRecord(
                chunk_id=span.chunk_id,
                document_id=document.document_id,
                source_id=document.source_id,
                company_name=document.company_name,
                chunk_index=chunk_index,
                text=span.text,
                start_offset=span.start_offset,
                end_offset=span.end_offset,
                content_checksum=span.content_checksum,
                document_type=document.document_type,
                source_url=document.source_url,
                filing_type=document.filing_type,
                filing_date=document.filing_date,
                fiscal_period=document.fiscal_period,
            )
        )

        if end_offset == text_length:
            break

        start_offset = end_offset - overlap_size
        chunk_index += 1

    return tuple(chunks)


def _build_chunk_span(
    *,
    document: DocumentRecord,
    chunk_index: int,
    start_offset: int,
    end_offset: int,
    chunk_text: str,
) -> _ChunkSpan:
    checksum = sha256_text(chunk_text)
    chunk_id = sha256_text(
        f"{document.document_id}|{document.source_id}|{chunk_index}|{start_offset}|{end_offset}|{checksum}"
    )
    return _ChunkSpan(
        start_offset=start_offset,
        end_offset=end_offset,
        chunk_index=chunk_index,
        text=chunk_text,
        content_checksum=checksum,
        chunk_id=chunk_id,
    )


def _require_document(document: object) -> None:
    if not isinstance(document, DocumentRecord):
        raise DocumentChunkingInputError("document must be a DocumentRecord instance.")
    if not isinstance(document.document_id, str) or not document.document_id.strip():
        raise DocumentChunkingInputError("document_id must not be empty.")
    if not isinstance(document.source_id, str) or not document.source_id.strip():
        raise DocumentChunkingInputError("source_id must not be empty.")


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChunkConfigurationError(f"{field_name} must be an integer.")
    if value <= 0:
        raise ChunkConfigurationError(f"{field_name} must be positive.")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChunkConfigurationError(f"{field_name} must be an integer.")
    if value < 0:
        raise ChunkConfigurationError(f"{field_name} must be zero or positive.")
    return value
