"""OpenAI embedding provider-specific DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be zero or positive.")
    return value


def _normalize_vector(values: object) -> tuple[float, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("embedding must be an ordered collection of numeric values.")
    if not values:
        raise ValueError("embedding must not be empty.")

    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding values must be numeric.")
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("embedding values must be finite.")
        normalized.append(numeric)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingUsageDTO:
    """Validated OpenAI embedding usage metadata."""

    prompt_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        prompt_tokens = _require_non_negative_int(self.prompt_tokens, "prompt_tokens")
        total_tokens = _require_non_negative_int(self.total_tokens, "total_tokens")
        if total_tokens < prompt_tokens:
            raise ValueError("total_tokens must be greater than or equal to prompt_tokens.")
        object.__setattr__(self, "prompt_tokens", prompt_tokens)
        object.__setattr__(self, "total_tokens", total_tokens)


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingItemDTO:
    """Validated OpenAI embedding item."""

    index: int
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        index = _require_non_negative_int(self.index, "index")
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "embedding", _normalize_vector(self.embedding))


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingsResponseDTO:
    """Validated OpenAI embeddings response."""

    model: str
    data: tuple[OpenAIEmbeddingItemDTO, ...]
    usage: OpenAIEmbeddingUsageDTO

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        object.__setattr__(self, "model", self.model.strip())

        if not isinstance(self.data, (list, tuple)):
            raise ValueError("data must be an ordered collection of OpenAIEmbeddingItemDTO instances.")
        normalized_data = tuple(self.data)
        if not normalized_data:
            raise ValueError("data must not be empty.")
        for item in normalized_data:
            if not isinstance(item, OpenAIEmbeddingItemDTO):
                raise ValueError("data must contain OpenAIEmbeddingItemDTO instances.")

        if not isinstance(self.usage, OpenAIEmbeddingUsageDTO):
            raise ValueError("usage must be an OpenAIEmbeddingUsageDTO instance.")

        indexes = [item.index for item in normalized_data]
        if indexes != list(range(len(normalized_data))):
            raise ValueError("data indexes must be sequential, unique, and start at zero.")

        dimensions = len(normalized_data[0].embedding)
        if dimensions <= 0:
            raise ValueError("embedding vectors must not be empty.")
        for item in normalized_data[1:]:
            if len(item.embedding) != dimensions:
                raise ValueError("embedding vectors must have consistent dimensions.")

        object.__setattr__(self, "data", normalized_data)
