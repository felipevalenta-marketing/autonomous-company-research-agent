"""Unit tests for OpenAI embedding DTO validation and serialization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.openai_embedding_dtos import (
    OpenAIEmbeddingItemDTO,
    OpenAIEmbeddingUsageDTO,
    OpenAIEmbeddingsResponseDTO,
)


class OpenAIEmbeddingDtoTests(unittest.TestCase):
    """Validation and serialization checks for OpenAI embedding DTOs."""

    def test_valid_item_usage_and_response_are_serializable(self) -> None:
        item = OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2, 0.3))
        usage = OpenAIEmbeddingUsageDTO(prompt_tokens=12, total_tokens=12)
        response = OpenAIEmbeddingsResponseDTO(
            model="text-embedding-3-small",
            data=(item,),
            usage=usage,
        )

        json.dumps(asdict(item))
        json.dumps(asdict(usage))
        json.dumps(asdict(response))
        self.assertEqual(response.data[0].embedding, (0.1, 0.2, 0.3))

    def test_empty_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=0, embedding=())

    def test_nonnumeric_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=0, embedding=("bad",))

    def test_boolean_vector_value_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=0, embedding=(True,))

    def test_nan_vector_value_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=0, embedding=(float("nan"),))

    def test_infinity_vector_value_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=0, embedding=(float("inf"),))

    def test_negative_index_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingItemDTO(index=-1, embedding=(0.1,))

    def test_duplicate_response_index_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingsResponseDTO(
                model="text-embedding-3-small",
                data=(
                    OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),
                    OpenAIEmbeddingItemDTO(index=0, embedding=(0.3, 0.4)),
                ),
                usage=OpenAIEmbeddingUsageDTO(prompt_tokens=4, total_tokens=4),
            )

    def test_malformed_response_rejection(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingsResponseDTO(
                model="text-embedding-3-small",
                data=(object(),),  # type: ignore[arg-type]
                usage=OpenAIEmbeddingUsageDTO(prompt_tokens=4, total_tokens=4),
            )

    def test_invalid_usage_values_reject(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIEmbeddingUsageDTO(prompt_tokens=5, total_tokens=4)

