"""Safe file-system helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile


def ensure_directory(path: str | Path) -> Path:
    """Create a directory if it does not already exist."""

    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_join(base_path: str | Path, *parts: str) -> Path:
    """Join path fragments while preventing traversal outside the base path."""

    base = Path(base_path).resolve()
    candidate = base.joinpath(*parts).resolve()
    if base != candidate and base not in candidate.parents:
        raise ValueError("resolved path escapes the base directory.")
    return candidate


def atomic_write_text(path: str | Path, content: str) -> Path:
    """Write text atomically to disk."""

    destination = Path(path)
    ensure_directory(destination.parent)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=destination.parent) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
    return destination
