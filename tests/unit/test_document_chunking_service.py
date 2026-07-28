"""Unit tests for deterministic document chunking."""

from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from app.models.chunks import ChunkRecord
from app.models.documents import DocumentRecord
from app.services.document_chunking_service import (
    ChunkConfigurationError,
    ChunkValidationError,
    DocumentChunkingInputError,
    chunk_document,
)


class DocumentChunkingServiceTests(unittest.TestCase):
    """Offline tests for deterministic fixed-size chunking."""

    def _build_document(self, *, content: str = "abcdefghij", document_id: str = "doc-1") -> DocumentRecord:
        return DocumentRecord(
            document_id=document_id,
            company_name="Apple Inc.",
            source_id="source-1",
            document_type="sec_filing",
            title="Quarterly filing",
            content=content,
            source_url="https://example.com/doc",
            filing_type="10-Q",
            filing_date="2026-07-23",
            fiscal_period="2026-Q2",
        )

    def _build_malformed_document(self, **overrides: object) -> DocumentRecord:
        document = object.__new__(DocumentRecord)
        values = {
            "document_id": "doc-1",
            "company_name": "Apple Inc.",
            "source_id": "source-1",
            "document_type": "sec_filing",
            "title": "Quarterly filing",
            "content": "abcdefghij",
            "storage_path": None,
            "source_url": "https://example.com/doc",
            "filing_type": "10-Q",
            "filing_date": "2026-07-23",
            "fiscal_period": "2026-Q2",
            "extraction_status": "pending",
            "chunk_count": 0,
        }
        values.update(overrides)
        for field_name, value in values.items():
            object.__setattr__(document, field_name, value)
        return document

    def test_valid_document_records_are_chunked(self) -> None:
        document = self._build_document(content="abcdefghij")

        chunks = chunk_document(document, chunk_size=5, overlap=2)

        self.assertIsInstance(chunks, tuple)
        self.assertTrue(all(isinstance(chunk, ChunkRecord) for chunk in chunks))
        self.assertEqual(len(chunks), 3)
        self.assertEqual([chunk.chunk_index for chunk in chunks], [0, 1, 2])
        self.assertEqual([chunk.start_offset for chunk in chunks], [0, 3, 6])
        self.assertEqual([chunk.end_offset for chunk in chunks], [5, 8, 10])
        self.assertEqual([chunk.text for chunk in chunks], ["abcde", "defgh", "ghij"])
        self.assertEqual(chunks[0].document_id, "doc-1")
        self.assertEqual(chunks[0].source_id, "source-1")
        self.assertEqual(chunks[0].company_name, "Apple Inc.")
        self.assertEqual(chunks[0].source_url, "https://example.com/doc")
        self.assertEqual(chunks[0].filing_type, "10-Q")
        self.assertEqual(chunks[0].filing_date, "2026-07-23")
        self.assertEqual(chunks[0].fiscal_period, "2026-Q2")

    def test_short_document_creates_single_chunk(self) -> None:
        document = self._build_document(content="abc")

        chunks = chunk_document(document, chunk_size=5, overlap=1)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].start_offset, 0)
        self.assertEqual(chunks[0].end_offset, 3)
        self.assertEqual(chunks[0].text, "abc")

    def test_exact_size_document_creates_single_chunk(self) -> None:
        document = self._build_document(content="abcde")

        chunks = chunk_document(document, chunk_size=5, overlap=2)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "abcde")
        self.assertEqual(chunks[0].start_offset, 0)
        self.assertEqual(chunks[0].end_offset, 5)

    def test_final_short_chunk_is_included(self) -> None:
        document = self._build_document(content="abcdefghijk")

        chunks = chunk_document(document, chunk_size=5, overlap=2)

        self.assertEqual([chunk.text for chunk in chunks], ["abcde", "defgh", "ghijk"])
        self.assertEqual(chunks[-1].end_offset, len(document.content or ""))

    def test_text_one_character_over_chunk_size(self) -> None:
        document = self._build_document(content="abcdef")

        chunks = chunk_document(document, chunk_size=5, overlap=2)

        self.assertEqual([chunk.text for chunk in chunks], ["abcde", "def"])
        self.assertEqual([chunk.start_offset for chunk in chunks], [0, 3])
        self.assertEqual([chunk.end_offset for chunk in chunks], [5, 6])

    def test_offsets_match_source_slices(self) -> None:
        document = self._build_document(content="ab\ncdef\tghij")

        chunks = chunk_document(document, chunk_size=4, overlap=1)

        for chunk in chunks:
            self.assertEqual(chunk.text, document.content[chunk.start_offset:chunk.end_offset])
            self.assertGreaterEqual(chunk.start_offset, 0)
            self.assertGreater(chunk.end_offset, chunk.start_offset)
        self.assertEqual(chunks[-1].end_offset, len(document.content or ""))

    def test_unicode_and_multiline_content_preserved(self) -> None:
        content = "café\nnaïve\temoji: 😀 — done."
        document = self._build_document(content=content)

        chunks = chunk_document(document, chunk_size=8, overlap=3)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.text, content[chunk.start_offset:chunk.end_offset])
        self.assertIn("é", "".join(chunk.text for chunk in chunks))
        self.assertIn("😀", "".join(chunk.text for chunk in chunks))
        self.assertIn("\n", content)
        self.assertIn("\t", content)

    def test_overlap_is_respected(self) -> None:
        document = self._build_document(content="abcdefghij")

        chunks = chunk_document(document, chunk_size=4, overlap=1)

        self.assertEqual([chunk.start_offset for chunk in chunks[1:]], [chunk.end_offset - 1 for chunk in chunks[:-1]])

    def test_invalid_input_type_rejected(self) -> None:
        with self.assertRaises(DocumentChunkingInputError):
            chunk_document("not-a-document")  # type: ignore[arg-type]

    def test_blank_document_id_rejected(self) -> None:
        document = self._build_malformed_document(document_id=" ")

        with self.assertRaises(DocumentChunkingInputError):
            chunk_document(document)

    def test_blank_source_id_rejected(self) -> None:
        document = self._build_malformed_document(source_id=" ")

        with self.assertRaises(DocumentChunkingInputError):
            chunk_document(document)

    def test_missing_or_blank_content_rejected(self) -> None:
        document = self._build_document(content="  ")

        with self.assertRaises(DocumentChunkingInputError):
            chunk_document(document)

    def test_nonstring_content_rejected(self) -> None:
        document = self._build_malformed_document(content=123)

        with self.assertRaises(DocumentChunkingInputError):
            chunk_document(document)  # type: ignore[arg-type]

    def test_invalid_chunk_size_rejected(self) -> None:
        document = self._build_document()

        for invalid in (0, -1, True, "5"):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(ChunkConfigurationError):
                    chunk_document(document, chunk_size=invalid, overlap=1)  # type: ignore[arg-type]

    def test_invalid_overlap_rejected(self) -> None:
        document = self._build_document()

        for invalid in (-1, True, "1"):  # type: ignore[list-item]
            with self.subTest(invalid=invalid):
                with self.assertRaises(ChunkConfigurationError):
                    chunk_document(document, chunk_size=5, overlap=invalid)  # type: ignore[arg-type]

        with self.assertRaises(ChunkConfigurationError):
            chunk_document(document, chunk_size=5, overlap=5)

        with self.assertRaises(ChunkConfigurationError):
            chunk_document(document, chunk_size=5, overlap=6)

    def test_one_character_chunk_size_with_zero_overlap(self) -> None:
        document = self._build_document(content="abc")

        chunks = chunk_document(document, chunk_size=1, overlap=0)

        self.assertEqual([chunk.text for chunk in chunks], ["a", "b", "c"])
        self.assertEqual([chunk.start_offset for chunk in chunks], [0, 1, 2])
        self.assertEqual([chunk.end_offset for chunk in chunks], [1, 2, 3])

    def test_high_valid_overlap_terminates(self) -> None:
        document = self._build_document(content="abcdef")

        chunks = chunk_document(document, chunk_size=4, overlap=3)

        self.assertEqual([chunk.text for chunk in chunks], ["abcd", "bcde", "cdef"])
        self.assertEqual([chunk.chunk_index for chunk in chunks], [0, 1, 2])

    def test_repeated_calls_are_deterministic(self) -> None:
        document = self._build_document(content="abcdefghij")

        first = chunk_document(document, chunk_size=5, overlap=2)
        second = chunk_document(document, chunk_size=5, overlap=2)

        self.assertEqual(first, second)
        self.assertEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])

    def test_document_id_changes_chunk_ids(self) -> None:
        first = chunk_document(self._build_document(document_id="doc-1"), chunk_size=5, overlap=2)
        second = chunk_document(self._build_document(document_id="doc-2"), chunk_size=5, overlap=2)

        self.assertNotEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])

    def test_text_changes_affected_chunk_ids(self) -> None:
        first = chunk_document(self._build_document(content="abcdefghij"), chunk_size=5, overlap=2)
        second = chunk_document(self._build_document(content="abcdEfghij"), chunk_size=5, overlap=2)

        self.assertNotEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])

    def test_chunk_size_changes_boundaries_and_ids(self) -> None:
        first = chunk_document(self._build_document(content="abcdefghij"), chunk_size=5, overlap=2)
        second = chunk_document(self._build_document(content="abcdefghij"), chunk_size=4, overlap=1)

        self.assertNotEqual([chunk.end_offset for chunk in first], [chunk.end_offset for chunk in second])
        self.assertNotEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])

    def test_no_shared_state_mutation(self) -> None:
        document = self._build_document()
        state = {"chunks": []}
        snapshot = dict(state)

        chunk_document(document, chunk_size=5, overlap=2)

        self.assertEqual(state, snapshot)

    def test_json_serializable(self) -> None:
        document = self._build_document()
        chunks = chunk_document(document, chunk_size=5, overlap=2)

        json.dumps([asdict(chunk) for chunk in chunks])

    def test_no_forbidden_imports_in_source(self) -> None:
        for path in ("app/services/document_chunking_service.py", "app/models/chunks.py"):
            source = Path(path).read_text(encoding="utf-8")
            for forbidden in (
                "openai",
                "pinecone",
                "langgraph",
                "app.models.state",
                "rag",
                "report",
                "prompts",
                "exporters",
                "n8n",
            ):
                self.assertNotIn(forbidden, source)

    def test_unicode_and_multiline_offsets_use_character_indexes(self) -> None:
        content = "café\nnaïve\temoji: 😀 — done."
        document = self._build_document(content=content)

        chunks = chunk_document(document, chunk_size=6, overlap=2)

        self.assertEqual(chunks[0].text, content[chunks[0].start_offset:chunks[0].end_offset])
        self.assertEqual(chunks[0].start_offset, 0)
        self.assertLessEqual(chunks[-1].end_offset, len(content))
        self.assertTrue(any("\n" in chunk.text for chunk in chunks))
        self.assertTrue(any("😀" in chunk.text for chunk in chunks))

    def test_signature_has_no_state_input(self) -> None:
        parameters = inspect.signature(chunk_document).parameters
        self.assertNotIn("state", parameters)
