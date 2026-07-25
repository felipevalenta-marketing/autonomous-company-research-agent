"""Tavily provider-specific DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from urllib.parse import urlsplit, urlunsplit


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _normalize_url(value: object) -> str:
    _require_text(value, "url")
    parsed = urlsplit(str(value).strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP or HTTPS URL.")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _normalize_score(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("score must not be empty.")
        try:
            score = float(stripped)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError("score must be numeric when provided.") from exc
    else:
        raise ValueError("score must be numeric when provided.")
    if not isfinite(score):
        raise ValueError("score must be finite when provided.")
    if score < 0:
        raise ValueError("score must be zero or positive.")
    return score


def _normalize_published_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("published_date must be a string when provided.")
    stripped = value.strip()
    if not stripped:
        raise ValueError("published_date must not be empty when provided.")
    if "T" in stripped:
        parsed_value = stripped.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(parsed_value)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError("published_date must be a valid ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            raise ValueError("published_date must include timezone information.")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        date.fromisoformat(stripped)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError("published_date must be a valid ISO-8601 date or timestamp.") from exc
    return stripped


@dataclass(frozen=True, slots=True)
class TavilySearchResultDTO:
    """Validated Tavily search result entry."""

    title: str
    url: str
    content: str | None = None
    score: float | None = None
    published_date: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "url", _normalize_url(self.url))
        object.__setattr__(self, "content", _optional_text(self.content))
        object.__setattr__(self, "score", _normalize_score(self.score))
        object.__setattr__(self, "published_date", _normalize_published_date(self.published_date))


@dataclass(frozen=True, slots=True)
class TavilySearchResponse:
    """Validated Tavily /search response."""

    query: str
    results: tuple[TavilySearchResultDTO, ...]
    answer: str | None = None
    response_time: float | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        object.__setattr__(self, "query", self.query.strip())
        object.__setattr__(self, "answer", _optional_text(self.answer))
        if self.response_time is not None:
            if not isinstance(self.response_time, (int, float)):
                raise ValueError("response_time must be zero or positive when provided.")
            response_time = float(self.response_time)
            if not isfinite(response_time) or response_time < 0:
                raise ValueError("response_time must be zero or positive when provided.")
            object.__setattr__(self, "response_time", response_time)
        object.__setattr__(self, "request_id", _optional_text(self.request_id))
        if not isinstance(self.results, tuple):
            raise ValueError("results must be a tuple of TavilySearchResultDTO instances.")
        for result in self.results:
            if not isinstance(result, TavilySearchResultDTO):
                raise ValueError("results must contain TavilySearchResultDTO instances.")
