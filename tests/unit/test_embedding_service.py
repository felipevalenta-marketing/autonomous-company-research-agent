"""Unit tests for the OpenAI embedding service."""

from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass
from pathlib import Path

from app.clients.openai_embedding_dtos import (
    OpenAIEmbeddingItemDTO,
    OpenAIEmbeddingUsageDTO,
)
from app.clients.openai_embeddings_client import OpenAIEmbeddingsRateLimitError
from app.services.embedding_service import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingRecord,
    embed_texts,
)
from app.utils.hashing import sha256_text


@dataclass(frozen=True, slots=True)
class FakeEmbeddingResponse:
    """In-memory embedding response."""

    model: str
    data: tuple[object, ...]
    usage: OpenAIEmbeddingUsageDTO


class FakeEmbeddingClient:
    """In-memory OpenAI embeddings client for offline orchestration tests."""

    def __init__(self, responses: tuple[object, ...]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create_embeddings(self, texts, model, dimensions=None):  # noqa: ANN001
        self.calls.append({"texts": tuple(texts) if not isinstance(texts, str) else (texts,), "model": model, "dimensions": dimensions})
        if not self._responses:
            raise AssertionError("No fake response configured.")
        return self._responses.pop(0)


class EmbeddingServiceTests(unittest.TestCase):
    """Offline tests for deterministic embedding orchestration."""

    def test_valid_single_input_returns_embedding_result(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2, 0.3)),),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=3, total_tokens=3),
                ),
            )
        )

        result = embed_texts("Hello embeddings", client)

        self.assertEqual(len(result.embeddings), 1)
        self.assertEqual(result.embeddings[0].input_index, 0)
        self.assertEqual(result.embeddings[0].input_checksum, sha256_text("Hello embeddings"))
        self.assertEqual(result.embeddings[0].vector_dimension, 3)
        self.assertEqual(client.calls[0]["texts"], ("Hello embeddings",))

    def test_valid_multiple_inputs_are_batched_and_preserve_order(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(
                        OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),
                        OpenAIEmbeddingItemDTO(index=1, embedding=(0.3, 0.4)),
                    ),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=4, total_tokens=4),
                ),
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.5, 0.6)),),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=2, total_tokens=2),
                ),
            )
        )

        result = embed_texts(("first", "second", "third"), client, batch_size=2)

        self.assertEqual([record.input_index for record in result.embeddings], [0, 1, 2])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["texts"], ("first", "second"))
        self.assertEqual(client.calls[1]["texts"], ("third",))

    def test_blank_input_rejection(self) -> None:
        client = FakeEmbeddingClient(())

        with self.assertRaises(EmbeddingInputError):
            embed_texts(" ", client)

    def test_empty_collection_rejection(self) -> None:
        client = FakeEmbeddingClient(())

        with self.assertRaises(EmbeddingInputError):
            embed_texts((), client)

    def test_deterministic_batching_uses_bounded_batch_size(self) -> None:
        responses = []
        for start in (0, 16):
            batch_size = 16 if start == 0 else 1
            items = tuple(
                OpenAIEmbeddingItemDTO(index=index, embedding=(float(index), float(index) + 1.0))
                for index in range(batch_size)
            )
            responses.append(
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=items,
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=batch_size * 2, total_tokens=batch_size * 2),
                )
            )
        client = FakeEmbeddingClient(tuple(responses))
        texts = tuple(f"text-{index}" for index in range(17))

        result = embed_texts(texts, client, batch_size=999)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(client.calls[0]["texts"]), 16)
        self.assertEqual(len(client.calls[1]["texts"]), 1)
        self.assertEqual(len(result.embeddings), 17)

    def test_response_count_mismatch_raises_batch_error(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=2, total_tokens=2),
                ),
            )
        )

        with self.assertRaises(EmbeddingBatchError):
            embed_texts(("first", "second"), client, batch_size=2)

    def test_response_index_mismatch_raises_batch_error(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(
                        type("Item", (), {"index": 1, "embedding": (0.1, 0.2)})(),
                        type("Item", (), {"index": 0, "embedding": (0.3, 0.4)})(),
                    ),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=4, total_tokens=4),
                ),
            )
        )

        with self.assertRaises(EmbeddingBatchError):
            embed_texts(("first", "second"), client, batch_size=2)

    def test_inconsistent_vector_dimensions_raise_dimension_error(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(
                        type("Item", (), {"index": 0, "embedding": (0.1, 0.2)})(),
                        type("Item", (), {"index": 1, "embedding": (0.3, 0.4, 0.5)})(),
                    ),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=4, total_tokens=4),
                ),
            )
        )

        with self.assertRaises(EmbeddingDimensionError):
            embed_texts(("first", "second"), client, batch_size=2)

    def test_expected_dimension_mismatch_raises_dimension_error(self) -> None:
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=2, total_tokens=2),
                ),
            )
        )

        with self.assertRaises(EmbeddingDimensionError):
            embed_texts("first", client, expected_dimension=3)

    def test_deterministic_repeated_output(self) -> None:
        responses = (
            FakeEmbeddingResponse(
                model="text-embedding-3-small",
                data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),),
                usage=OpenAIEmbeddingUsageDTO(prompt_tokens=2, total_tokens=2),
            ),
        )

        first = embed_texts("repeatable", FakeEmbeddingClient(responses))
        second = embed_texts("repeatable", FakeEmbeddingClient(responses))

        self.assertEqual(first, second)

    def test_client_errors_propagate(self) -> None:
        class ErrorClient(FakeEmbeddingClient):
            def create_embeddings(self, texts, model, dimensions=None):  # noqa: ANN001
                raise OpenAIEmbeddingsRateLimitError("rate limited")

        with self.assertRaises(OpenAIEmbeddingsRateLimitError):
            embed_texts("first", ErrorClient(()))

    def test_no_shared_state_or_forbidden_imports(self) -> None:
        state = {"embeddings": []}
        client = FakeEmbeddingClient(
            (
                FakeEmbeddingResponse(
                    model="text-embedding-3-small",
                    data=(OpenAIEmbeddingItemDTO(index=0, embedding=(0.1, 0.2)),),
                    usage=OpenAIEmbeddingUsageDTO(prompt_tokens=2, total_tokens=2),
                ),
            )
        )

        embed_texts("first", client)

        self.assertEqual(state, {"embeddings": []})
        module = importlib.import_module(embed_texts.__module__)
        module_source = Path(module.__file__).read_text(encoding="utf-8").lower()
        for line in module_source.splitlines():
            stripped = line.strip()
            self.assertFalse(stripped.startswith("import langgraph"))
            self.assertFalse(stripped.startswith("from langgraph"))
            self.assertFalse(stripped.startswith("import pinecone"))
            self.assertFalse(stripped.startswith("from pinecone"))
