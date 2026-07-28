"""Unit tests for chunk embedding orchestration."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from app.models.chunks import ChunkRecord
from app.services.chunk_embedding_service import (
    ChunkEmbeddingError,
    ChunkEmbeddingInputError,
    ChunkEmbeddingMappingError,
    ChunkEmbeddingResultError,
    EmbeddedChunkRecord,
    embed_chunks,
)
from app.services.embedding_service import (
    EmbeddingInputError,
    EmbeddingRecord,
    EmbeddingServiceResult,
)
from app.utils.hashing import sha256_text


class FakeEmbeddingService:
    """In-memory embedding service boundary used for offline orchestration tests."""

    def __init__(self, result: EmbeddingServiceResult) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, texts: tuple[str, ...]) -> EmbeddingServiceResult:
        self.calls.append(texts)
        return self.result


def _build_chunk(
    *,
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    source_id: str = "source-1",
    company_name: str = "Example Corp",
    chunk_index: int = 0,
    text: str = "alpha beta gamma",
    start_offset: int = 0,
    end_offset: int = 16,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        source_id=source_id,
        company_name=company_name,
        chunk_index=chunk_index,
        text=text,
        start_offset=start_offset,
        end_offset=end_offset,
        content_checksum=sha256_text(text),
        document_type="filing",
    )


def _build_malformed_chunk(**overrides: object) -> ChunkRecord:
    chunk = object.__new__(ChunkRecord)
    values = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "source_id": "source-1",
        "company_name": "Example Corp",
        "chunk_index": 0,
        "text": "alpha beta gamma",
        "start_offset": 0,
        "end_offset": 16,
        "content_checksum": sha256_text("alpha beta gamma"),
        "document_type": "filing",
        "source_url": None,
        "filing_type": None,
        "filing_date": None,
        "fiscal_period": None,
    }
    values.update(overrides)
    for field, value in values.items():
        object.__setattr__(chunk, field, value)
    return chunk


def _build_embedding_record(
    *,
    input_index: int,
    input_checksum: str,
    model: str = "text-embedding-3-small",
    vector: tuple[float, ...] = (0.1, 0.2, 0.3),
) -> EmbeddingRecord:
    return EmbeddingRecord(
        input_index=input_index,
        input_checksum=input_checksum,
        model=model,
        vector_dimension=len(vector),
        vector=vector,
    )


def _build_malformed_embedding_record(**overrides: object) -> EmbeddingRecord:
    record = object.__new__(EmbeddingRecord)
    values = {
        "input_index": 0,
        "input_checksum": sha256_text("alpha beta gamma"),
        "model": "text-embedding-3-small",
        "vector_dimension": 3,
        "vector": (0.1, 0.2, 0.3),
    }
    values.update(overrides)
    for field, value in values.items():
        object.__setattr__(record, field, value)
    return record


def _build_result(*embeddings: EmbeddingRecord, model: str = "text-embedding-3-small") -> EmbeddingServiceResult:
    return EmbeddingServiceResult(model=model, embeddings=tuple(embeddings))


def _build_malformed_result(*embeddings: EmbeddingRecord, model: str = "text-embedding-3-small") -> EmbeddingServiceResult:
    result = object.__new__(EmbeddingServiceResult)
    object.__setattr__(result, "model", model)
    object.__setattr__(result, "embeddings", tuple(embeddings))
    return result


class ChunkEmbeddingServiceTests(unittest.TestCase):
    """Offline tests for chunk embedding orchestration."""

    def test_valid_tuple_of_chunks_embeds_and_preserves_order(self) -> None:
        chunks = (
            _build_chunk(chunk_id="chunk-1", chunk_index=0, text="alpha beta", end_offset=10),
            _build_chunk(chunk_id="chunk-2", chunk_index=1, text="gamma delta", start_offset=6, end_offset=17),
        )
        result = _build_result(
            _build_embedding_record(input_index=0, input_checksum=sha256_text("alpha beta"), vector=(0.1, 0.2)),
            _build_embedding_record(input_index=1, input_checksum=sha256_text("gamma delta"), vector=(0.3, 0.4)),
        )
        service = FakeEmbeddingService(result)

        embedded = embed_chunks(chunks, service)

        self.assertEqual(service.calls, [("alpha beta", "gamma delta")])
        self.assertEqual(len(embedded), 2)
        self.assertIsInstance(embedded[0], EmbeddedChunkRecord)
        self.assertIs(embedded[0].chunk, chunks[0])
        self.assertIs(embedded[1].chunk, chunks[1])
        self.assertEqual(embedded[0].embedding.vector, (0.1, 0.2))
        self.assertEqual(embedded[1].embedding.vector, (0.3, 0.4))

    def test_wrong_collection_type_rejected(self) -> None:
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text("alpha beta gamma"))))

        with self.assertRaises(ChunkEmbeddingInputError):
            embed_chunks([_build_chunk()], service)  # type: ignore[arg-type]

    def test_non_chunk_record_element_rejected(self) -> None:
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text("alpha beta gamma"))))

        with self.assertRaises(ChunkEmbeddingInputError):
            embed_chunks((_build_chunk(), object()), service)  # type: ignore[arg-type]

    def test_duplicate_chunk_id_rejected(self) -> None:
        chunk = _build_chunk()
        duplicate = replace(chunk, chunk_index=1, start_offset=8, end_offset=16)
        service = FakeEmbeddingService(
            _build_result(
                _build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text), vector=(0.1, 0.2, 0.3)),
                _build_embedding_record(input_index=1, input_checksum=sha256_text(duplicate.text), vector=(0.4, 0.5, 0.6)),
            )
        )

        with self.assertRaises(ChunkEmbeddingInputError):
            embed_chunks((chunk, replace(duplicate, chunk_id=chunk.chunk_id)), service)

    def test_blank_chunk_text_rejected(self) -> None:
        chunk = _build_malformed_chunk(text=" ")
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text("alpha beta gamma"))))

        with self.assertRaises(ChunkEmbeddingInputError):
            embed_chunks((chunk,), service)

    def test_input_tuple_remains_unchanged(self) -> None:
        chunk = _build_chunk()
        chunks = (chunk,)
        snapshot = chunks
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))

        embed_chunks(chunks, service)

        self.assertIs(chunks, snapshot)
        self.assertEqual(chunks[0], chunk)

    def test_empty_input_returns_empty_tuple_without_call(self) -> None:
        service = FakeEmbeddingService(
            _build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text("alpha beta gamma")))
        )

        embedded = embed_chunks((), service)

        self.assertEqual(embedded, ())
        self.assertEqual(service.calls, [])

    def test_embedding_service_called_exactly_once(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))

        embed_chunks((chunk,), service)

        self.assertEqual(len(service.calls), 1)

    def test_embedding_failure_is_wrapped(self) -> None:
        class ErrorService:
            def __call__(self, texts: tuple[str, ...]) -> EmbeddingServiceResult:
                raise EmbeddingInputError("nope")

        with self.assertRaises(ChunkEmbeddingError):
            embed_chunks((_build_chunk(),), ErrorService())

    def test_matching_embedding_count_required(self) -> None:
        chunk = _build_chunk()
        result = _build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text)))
        service = FakeEmbeddingService(result)

        embedded = embed_chunks((chunk,), service)

        self.assertEqual(len(embedded), 1)

    def test_fewer_embedding_records_rejected(self) -> None:
        chunk1 = _build_chunk(chunk_id="chunk-1", chunk_index=0, text="alpha beta", end_offset=10)
        chunk2 = _build_chunk(chunk_id="chunk-2", chunk_index=1, text="gamma delta", start_offset=6, end_offset=17)
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk1.text)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk1, chunk2), service)

    def test_extra_embedding_records_rejected(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text)),
                _build_malformed_embedding_record(input_index=1, input_checksum=sha256_text(chunk.text), vector=(0.4, 0.5, 0.6)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_duplicate_input_index_rejected(self) -> None:
        chunk1 = _build_chunk(chunk_id="chunk-1", chunk_index=0, text="alpha beta", end_offset=10)
        chunk2 = _build_chunk(chunk_id="chunk-2", chunk_index=1, text="gamma delta", start_offset=6, end_offset=17)
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk1.text)),
                _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk2.text)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk1, chunk2), service)

    def test_negative_input_index_rejected(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=-1, input_checksum=sha256_text(chunk.text)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_out_of_range_input_index_rejected(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=1, input_checksum=sha256_text(chunk.text)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_boolean_input_index_rejected(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=True, input_checksum=sha256_text(chunk.text)),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_missing_index_rejected(self) -> None:
        chunk = _build_chunk()
        embedding = _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))
        object.__setattr__(embedding, "input_index", None)
        service = FakeEmbeddingService(_build_malformed_result(embedding))

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_checksum_mismatch_raises_mapping_error(self) -> None:
        chunk = _build_chunk(text="alpha beta", end_offset=10)
        embedding = _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text("different text"))
        service = FakeEmbeddingService(_build_malformed_result(embedding))

        with self.assertRaises(ChunkEmbeddingMappingError):
            embed_chunks((chunk,), service)

    def test_shuffled_embedding_response_is_mapped_by_index(self) -> None:
        chunk1 = _build_chunk(chunk_id="chunk-1", chunk_index=0, text="alpha beta", end_offset=10)
        chunk2 = _build_chunk(chunk_id="chunk-2", chunk_index=1, text="gamma delta", start_offset=6, end_offset=17)
        result = _build_malformed_result(
            _build_malformed_embedding_record(
                input_index=1,
                input_checksum=sha256_text(chunk2.text),
                vector=(0.3, 0.4),
                vector_dimension=2,
            ),
            _build_malformed_embedding_record(
                input_index=0,
                input_checksum=sha256_text(chunk1.text),
                vector=(0.1, 0.2),
                vector_dimension=2,
            ),
        )
        service = FakeEmbeddingService(result)

        embedded = embed_chunks((chunk1, chunk2), service)

        self.assertEqual([record.chunk.chunk_id for record in embedded], ["chunk-1", "chunk-2"])
        self.assertEqual([record.embedding.vector for record in embedded], [(0.1, 0.2), (0.3, 0.4)])

    def test_empty_vector_rejected(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text), vector=(), vector_dimension=0),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_invalid_vector_rejected_through_existing_contracts(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(
            _build_malformed_result(
                _build_malformed_embedding_record(
                    input_index=0,
                    input_checksum=sha256_text(chunk.text),
                    vector=(0.1, True),
                    vector_dimension=2,
                ),
            )
        )

        with self.assertRaises(ChunkEmbeddingResultError):
            embed_chunks((chunk,), service)

    def test_repeated_calls_are_deterministic(self) -> None:
        chunk = _build_chunk()
        service_one = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))
        service_two = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))

        first = embed_chunks((chunk,), service_one)
        second = embed_chunks((chunk,), service_two)

        self.assertEqual(first, second)
        self.assertEqual(first[0].chunk.chunk_id, chunk.chunk_id)

    def test_no_shared_state_mutation(self) -> None:
        state = {"embedded_chunks": []}
        chunk = _build_chunk()
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))

        embed_chunks((chunk,), service)

        self.assertEqual(state, {"embedded_chunks": []})

    def test_json_serializable(self) -> None:
        chunk = _build_chunk()
        service = FakeEmbeddingService(_build_result(_build_embedding_record(input_index=0, input_checksum=sha256_text(chunk.text))))

        embedded = embed_chunks((chunk,), service)
        payload = json.dumps(
            [
                {
                    "chunk": {
                        "chunk_id": record.chunk.chunk_id,
                        "document_id": record.chunk.document_id,
                        "source_id": record.chunk.source_id,
                        "company_name": record.chunk.company_name,
                        "chunk_index": record.chunk.chunk_index,
                        "text": record.chunk.text,
                        "start_offset": record.chunk.start_offset,
                        "end_offset": record.chunk.end_offset,
                        "content_checksum": record.chunk.content_checksum,
                        "document_type": record.chunk.document_type,
                    },
                    "embedding": {
                        "input_index": record.embedding.input_index,
                        "input_checksum": record.embedding.input_checksum,
                        "model": record.embedding.model,
                        "vector_dimension": record.embedding.vector_dimension,
                        "vector": record.embedding.vector,
                    },
                }
                for record in embedded
            ]
        )

        self.assertIn("chunk_id", payload)

    def test_no_forbidden_imports_in_source(self) -> None:
        with open("app/services/chunk_embedding_service.py", encoding="utf-8") as handle:
            source = handle.read()

        for forbidden in ("openai", "pinecone", "langgraph", "app.models.state", "app.rag", "report", "prompts", "exporters", "n8n"):
            self.assertNotIn(forbidden, source)

        self.assertNotIn("OpenAIEmbeddingsClient(", source)
        self.assertNotIn("PineconeClient(", source)
