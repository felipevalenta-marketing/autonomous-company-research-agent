"""Canonical source registration helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.sources import SourceRecord


def register_sources(*source_groups: Iterable[SourceRecord]) -> tuple[SourceRecord, ...]:
    """Deterministically upsert canonical source records by identifier."""

    registered_sources: dict[str, SourceRecord] = {}
    for source_group in source_groups:
        for source in source_group:
            registered_sources[source.source_id] = source
    return tuple(registered_sources.values())
