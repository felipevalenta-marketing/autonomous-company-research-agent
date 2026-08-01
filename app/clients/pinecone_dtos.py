"""Pinecone provider-specific DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")
    return value.strip()


def _normalize_vector(values: object) -> tuple[float, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("vector values must be provided as an ordered collection.")
    if not values:
        raise ValueError("vector values must not be empty.")

    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("vector values must be numeric.")
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("vector values must be finite.")
        normalized.append(numeric)
    return tuple(normalized)


def _normalize_metadata_value(value: object, *, key: str | None = None) -> object:
    if key == "text_id":
        if not isinstance(value, str):
            raise ValueError("metadata values must be JSON-compatible scalars or flat lists.")
        return value
    if value is None:
        raise ValueError("metadata values must not be null.")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("metadata values must be finite.")
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("metadata values must not be empty.")
        return stripped
    if isinstance(value, (list, tuple)):
        normalized_list: list[object] = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)):
                raise ValueError("metadata lists must be flat and JSON-compatible.")
            normalized_list.append(_normalize_metadata_value(item))
        return tuple(normalized_list)
    raise ValueError("metadata values must be JSON-compatible scalars or flat lists.")


def _normalize_metadata(metadata: object) -> dict[str, object]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping.")

    normalized: dict[str, object] = {}
    for key, value in metadata.items():
        normalized_key = _require_text(key, "metadata key")
        if normalized_key in normalized:
            raise ValueError("metadata keys must be unique.")
        normalized[normalized_key] = _normalize_metadata_value(value, key=normalized_key)
    return normalized


def _normalize_namespace(namespace: object | None) -> str | None:
    if namespace is None:
        return None
    return _require_text(namespace, "namespace")


def _normalize_score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be numeric.")
    score = float(value)
    if not isfinite(score):
        raise ValueError("score must be finite.")
    return score


@dataclass(frozen=True, slots=True)
class PineconeVectorRecordDTO:
    """Validated Pinecone vector record."""

    record_id: str
    values: tuple[float, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _require_text(self.record_id, "record_id"))
        object.__setattr__(self, "values", _normalize_vector(self.values))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class PineconeUpsertResultDTO:
    """Technical acknowledgement for a Pinecone upsert."""

    namespace: str
    upserted_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_text(self.namespace, "namespace"))
        if isinstance(self.upserted_count, bool) or not isinstance(self.upserted_count, int):
            raise ValueError("upserted_count must be an integer.")
        if self.upserted_count < 0:
            raise ValueError("upserted_count must be zero or positive.")


@dataclass(frozen=True, slots=True)
class PineconeDeleteResultDTO:
    """Technical acknowledgement for a Pinecone delete."""

    namespace: str
    deleted_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_text(self.namespace, "namespace"))
        if isinstance(self.deleted_count, bool) or not isinstance(self.deleted_count, int):
            raise ValueError("deleted_count must be an integer.")
        if self.deleted_count < 0:
            raise ValueError("deleted_count must be zero or positive.")


@dataclass(frozen=True, slots=True)
class PineconeQueryMatchDTO:
    """Validated Pinecone query match."""

    record_id: str
    score: float
    metadata: dict[str, object] = field(default_factory=dict)
    values: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _require_text(self.record_id, "record_id"))
        object.__setattr__(self, "score", _normalize_score(self.score))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))
        if self.values is not None:
            object.__setattr__(self, "values", _normalize_vector(self.values))


@dataclass(frozen=True, slots=True)
class PineconeQueryResponseDTO:
    """Validated Pinecone query response."""

    matches: tuple[PineconeQueryMatchDTO, ...] = field(default_factory=tuple)
    namespace: str | None = None

    def __post_init__(self) -> None:
        namespace = _normalize_namespace(self.namespace)
        object.__setattr__(self, "namespace", namespace)
        if not isinstance(self.matches, (list, tuple)):
            raise ValueError("matches must be an ordered collection of PineconeQueryMatchDTO instances.")
        normalized_matches = tuple(self.matches)
        for match in normalized_matches:
            if not isinstance(match, PineconeQueryMatchDTO):
                raise ValueError("matches must contain PineconeQueryMatchDTO instances only.")
        record_ids = [match.record_id for match in normalized_matches]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("matches must not contain duplicate record IDs.")
        object.__setattr__(self, "matches", normalized_matches)
