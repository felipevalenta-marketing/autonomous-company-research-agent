"""Hashing helpers."""

from __future__ import annotations

from hashlib import sha256


def sha256_text(value: str) -> str:
    """Return the SHA-256 hex digest for text."""

    return sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    """Return the SHA-256 hex digest for bytes."""

    return sha256(value).hexdigest()

