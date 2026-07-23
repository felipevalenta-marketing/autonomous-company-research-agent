"""Identifier helpers."""

from __future__ import annotations

from uuid import uuid4


def new_execution_id(prefix: str = "exec") -> str:
    """Create a stable human-readable execution identifier."""

    return f"{prefix}_{uuid4().hex}"


def slugify(value: str) -> str:
    """Convert text into a lowercase safe identifier fragment."""

    normalized = [
        character.lower() if character.isalnum() else "_"
        for character in value.strip()
    ]
    slug = "".join(normalized)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")

