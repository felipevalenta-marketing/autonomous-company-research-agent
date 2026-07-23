"""Date helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""

    return datetime.now(UTC).isoformat()


def normalize_iso_datetime(value: str) -> str:
    """Normalize a datetime-like string by stripping whitespace."""

    normalized = value.strip()
    if not normalized:
        raise ValueError("datetime value must not be empty.")
    return normalized

