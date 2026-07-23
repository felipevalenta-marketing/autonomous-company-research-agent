"""Utility unit tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.utils.dates import normalize_iso_datetime, utc_now_iso
from app.utils.files import atomic_write_text, ensure_directory, safe_join
from app.utils.hashing import sha256_bytes, sha256_text
from app.utils.ids import new_execution_id, slugify
from app.utils.logging import configure_logging, redact_sensitive_text


class UtilityTests(unittest.TestCase):
    """Tests for framework-independent utility helpers."""

    def test_identifier_helpers(self) -> None:
        execution_id = new_execution_id("exec")
        self.assertTrue(execution_id.startswith("exec_"))
        self.assertEqual(slugify("Apple Inc."), "apple_inc")

    def test_date_helpers(self) -> None:
        now = utc_now_iso()
        self.assertTrue(now)
        self.assertEqual(normalize_iso_datetime(" 2026-07-23T00:00:00Z "), "2026-07-23T00:00:00Z")
        with self.assertRaises(ValueError):
            normalize_iso_datetime(" ")

    def test_hashing_helpers(self) -> None:
        self.assertEqual(sha256_text("hello"), sha256_bytes(b"hello"))

    def test_file_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = ensure_directory(Path(temp_dir) / "nested")
            target = safe_join(base, "report.txt")
            written = atomic_write_text(target, "hello world")
            self.assertTrue(written.exists())
            self.assertEqual(written.read_text(encoding="utf-8"), "hello world")
            with self.assertRaises(ValueError):
                safe_join(base, "..", "escape.txt")

    def test_logging_helpers(self) -> None:
        configure_logging()
        self.assertEqual(
            redact_sensitive_text("secret=abc123", secrets=["abc123"]),
            "secret=[REDACTED]",
        )

