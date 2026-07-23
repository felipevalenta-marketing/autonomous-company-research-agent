"""Logging helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterable


def configure_logging(level: int = logging.INFO) -> None:
    """Configure a basic application logger."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def redact_sensitive_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Redact exact secret values from a text payload."""

    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted

