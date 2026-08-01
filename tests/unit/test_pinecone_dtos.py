"""Unit tests for Pinecone DTO validation and serialization."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from app.clients.pinecone_dtos import (
    PineconeDeleteResultDTO,
    PineconeQueryMatchDTO,
    PineconeQueryResponseDTO,
    PineconeUpsertResultDTO,
    PineconeVectorRecordDTO,
)


class PineconeDtoTests(unittest.TestCase):
    """Validation and serialization checks for Pinecone DTOs."""

    def test_valid_vector_record_is_serializable(self) -> None:
        record = PineconeVectorRecordDTO(
            record_id="vec-1",
            values=(0.1, 0.2, 0.3),
            metadata={"company_name": "Apple", "source_ids": ["source-1", "source-2"]},
        )

        json.dumps(asdict(record))
        self.assertEqual(record.values, (0.1, 0.2, 0.3))
        self.assertEqual(record.metadata["company_name"], "Apple")

    def test_text_id_metadata_is_preserved_verbatim(self) -> None:
        record = PineconeVectorRecordDTO(
            record_id="vec-1",
            values=(0.1, 0.2, 0.3),
            metadata={
                "text_id": "  alpha\nbeta\t  ",
                "company_name": " Apple ",
            },
        )

        self.assertEqual(record.metadata["text_id"], "  alpha\nbeta\t  ")
        self.assertEqual(record.metadata["company_name"], "Apple")

    def test_blank_id_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id=" ", values=(0.1,))

    def test_empty_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=())

    def test_nonnumeric_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=("bad",))

    def test_boolean_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=(True,))

    def test_nan_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=(float("nan"),))

    def test_infinity_vector_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=(float("inf"),))

    def test_invalid_metadata_key_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=(0.1,), metadata={" ": "value"})

    def test_invalid_metadata_value_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeVectorRecordDTO(record_id="vec-1", values=(0.1,), metadata={"source": {"nested": "value"}})

    def test_valid_query_match_is_serializable(self) -> None:
        match = PineconeQueryMatchDTO(
            record_id="vec-1",
            score=0.75,
            metadata={"source_id": "source-1"},
            values=(0.1, 0.2),
        )
        response = PineconeQueryResponseDTO(matches=(match,), namespace="company:cik:abc")

        json.dumps(asdict(match))
        json.dumps(asdict(response))
        self.assertEqual(response.matches[0].record_id, "vec-1")

    def test_non_finite_score_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeQueryMatchDTO(record_id="vec-1", score=float("inf"))

    def test_duplicate_match_id_rejection(self) -> None:
        with self.assertRaises(ValueError):
            PineconeQueryResponseDTO(
                matches=(
                    PineconeQueryMatchDTO(record_id="vec-1", score=0.9),
                    PineconeQueryMatchDTO(record_id="vec-1", score=0.8),
                ),
                namespace="company:cik:abc",
            )

    def test_upsert_and_delete_acknowledgements_are_serializable(self) -> None:
        json.dumps(asdict(PineconeUpsertResultDTO(namespace="company:cik:abc", upserted_count=2)))
        json.dumps(asdict(PineconeDeleteResultDTO(namespace="company:cik:abc", deleted_count=1)))
