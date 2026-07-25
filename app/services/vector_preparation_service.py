"""Vector preparation helpers for Pinecone indexing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.clients.pinecone_dtos import PineconeVectorRecordDTO
from app.config.constants import PINECONE_DEFAULT_NAMESPACE_PREFIX
from app.models.company import ResolvedCompany
from app.services.embedding_service import EmbeddingRecord, EmbeddingServiceResult
from app.utils.hashing import sha256_text
from app.utils.ids import slugify


class VectorPreparationError(Exception):
    """Base exception for Pinecone vector preparation failures."""


class VectorPreparationInputError(VectorPreparationError):
    """Raised when vector preparation inputs are invalid."""


class VectorMetadataError(VectorPreparationError):
    """Raised when approved Pinecone metadata cannot be normalized."""


class VectorDimensionError(VectorPreparationError):
    """Raised when vector dimensions are inconsistent or unexpected."""


_ALLOWED_METADATA_KEYS = {
    "company_name",
    "ticker",
    "cik",
    "document_id",
    "source_id",
    "source_url",
    "provider_name",
    "filing_form",
    "filing_date",
    "report_date",
    "content_checksum",
    "text_id",
    "chunk_id",
    "input_index",
    "input_checksum",
    "embedding_model",
    "vector_dimension",
    "record_id",
}


def build_pinecone_namespace(
    resolved_company: ResolvedCompany,
    namespace_prefix: str | None = None,
) -> str:
    """Build a deterministic company-scoped Pinecone namespace."""

    if not isinstance(resolved_company, ResolvedCompany):
        raise VectorPreparationInputError("resolved_company must be a ResolvedCompany instance.")

    prefix = slugify(namespace_prefix or PINECONE_DEFAULT_NAMESPACE_PREFIX) or slugify(PINECONE_DEFAULT_NAMESPACE_PREFIX)
    identity_kind, identity_value = _select_company_identity(resolved_company)
    seed = f"{identity_kind}:{_normalize_identity_value(identity_value)}"
    digest = sha256_text(seed)[:24]
    return f"{prefix}:{identity_kind}:{digest}"


def prepare_pinecone_vectors(
    embedding_result: EmbeddingServiceResult,
    record_identities: Sequence[str],
    metadata_entries: Sequence[Mapping[str, object]],
    *,
    expected_dimension: int | None = None,
) -> tuple[PineconeVectorRecordDTO, ...]:
    """Prepare deterministic Pinecone vector records for upsert."""

    if not isinstance(embedding_result, EmbeddingServiceResult):
        raise VectorPreparationInputError("embedding_result must be an EmbeddingServiceResult instance.")

    embeddings = tuple(embedding_result.embeddings)
    identities = _normalize_identities(record_identities)
    metadata_values = tuple(metadata_entries)
    if len(embeddings) != len(identities) or len(embeddings) != len(metadata_values):
        raise VectorPreparationInputError("embedding results, identities, and metadata entries must have the same length.")

    normalized_expected_dimension = _normalize_optional_positive_int(expected_dimension, "expected_dimension")
    vector_records: list[PineconeVectorRecordDTO] = []
    seen_record_ids: set[str] = set()

    for embedding, identity, metadata in zip(embeddings, identities, metadata_values, strict=True):
        if embedding.input_index != len(vector_records):
            raise VectorPreparationInputError("embedding_result must preserve sequential input indexes.")
        if normalized_expected_dimension is not None and embedding.vector_dimension != normalized_expected_dimension:
            raise VectorDimensionError("embedding vector dimension did not match the configured expectation.")

        normalized_metadata = _normalize_metadata(metadata)
        normalized_metadata.update(
            {
                "input_index": embedding.input_index,
                "input_checksum": embedding.input_checksum,
                "embedding_model": embedding.model,
                "vector_dimension": embedding.vector_dimension,
            }
        )
        record_id = _build_record_id(identity, embedding)
        if record_id in seen_record_ids:
            raise VectorPreparationInputError("prepared vector record IDs must be unique.")
        seen_record_ids.add(record_id)
        vector_records.append(
            PineconeVectorRecordDTO(
                record_id=record_id,
                values=embedding.vector,
                metadata=normalized_metadata,
            )
        )

    return tuple(vector_records)


def _build_record_id(identity: str, embedding: EmbeddingRecord) -> str:
    normalized_identity = _normalize_identity_value(identity)
    return sha256_text(f"{normalized_identity}|{embedding.input_checksum}")


def _normalize_identity_value(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorPreparationInputError("record identities must be non-empty strings.")
    return " ".join(value.split()).casefold()


def _normalize_identities(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise VectorPreparationInputError("record_identities must be an ordered collection of strings.")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise VectorPreparationInputError("record_identities must contain non-empty strings.")
        normalized_value = " ".join(value.split())
        if normalized_value in seen:
            raise VectorPreparationInputError("record_identities must not contain duplicates.")
        seen.add(normalized_value)
        normalized.append(normalized_value)
    if not normalized:
        raise VectorPreparationInputError("record_identities must not be empty.")
    return tuple(normalized)


def _normalize_optional_positive_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorPreparationInputError(f"{field_name} must be an integer when provided.")
    if value <= 0:
        raise VectorPreparationInputError(f"{field_name} must be positive when provided.")
    return value


def _normalize_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(metadata, Mapping):
        raise VectorMetadataError("metadata must be a mapping.")

    normalized: dict[str, object] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip():
            raise VectorMetadataError("metadata keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key not in _ALLOWED_METADATA_KEYS:
            raise VectorMetadataError("metadata keys must use the approved Pinecone contract.")
        if value is None:
            raise VectorMetadataError("metadata values must not be null.")
        if isinstance(value, Mapping):
            raise VectorMetadataError("metadata values must be JSON-compatible scalars or flat lists.")
        if isinstance(value, (list, tuple)):
            normalized[normalized_key] = _normalize_metadata_list(value)
            continue
        if isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        if isinstance(value, int):
            normalized[normalized_key] = value
            continue
        if isinstance(value, float):
            if not (value == value and value not in {float("inf"), float("-inf")}):
                raise VectorMetadataError("metadata numeric values must be finite.")
            normalized[normalized_key] = value
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise VectorMetadataError("metadata string values must not be empty.")
            normalized[normalized_key] = stripped
            continue
        raise VectorMetadataError("metadata values must be JSON-compatible.")
    return normalized


def _normalize_metadata_list(values: Sequence[object]) -> tuple[object, ...]:
    normalized: list[object] = []
    for value in values:
        if isinstance(value, Mapping) or isinstance(value, (list, tuple)):
            raise VectorMetadataError("metadata lists must be flat.")
        if value is None:
            raise VectorMetadataError("metadata lists must not contain null values.")
        if isinstance(value, bool):
            normalized.append(value)
        elif isinstance(value, int):
            normalized.append(value)
        elif isinstance(value, float):
            if not (value == value and value not in {float("inf"), float("-inf")}):
                raise VectorMetadataError("metadata list numeric values must be finite.")
            normalized.append(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise VectorMetadataError("metadata list string values must not be empty.")
            normalized.append(stripped)
        else:
            raise VectorMetadataError("metadata list values must be JSON-compatible.")
    return tuple(normalized)


def _select_company_identity(resolved_company: ResolvedCompany) -> tuple[str, str]:
    if resolved_company.cik and resolved_company.cik.strip():
        return "cik", resolved_company.cik
    if resolved_company.ticker and resolved_company.ticker.strip():
        return "ticker", resolved_company.ticker
    return "company", resolved_company.company_name
