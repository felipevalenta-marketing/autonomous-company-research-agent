"""NewsAPI provider-specific DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_timestamp(value: str) -> str:
    _require_text(value, "published_at")
    parsed_value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(parsed_value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError("published_at must be a valid ISO-8601 timestamp.") from exc

    if parsed.tzinfo is None:
        raise ValueError("published_at must include timezone information.")
    normalized = parsed.astimezone(UTC).isoformat()
    return normalized.replace("+00:00", "Z")


def _normalize_url(value: str) -> str:
    _require_text(value, "url")
    parsed = urlsplit(value.strip())
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


@dataclass(frozen=True, slots=True)
class NewsApiSourceDTO:
    """Validated NewsAPI article source metadata."""

    id: str | None
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _optional_text(self.id))
        _require_text(self.name, "name")
        object.__setattr__(self, "name", self.name.strip())


@dataclass(frozen=True, slots=True)
class NewsApiArticleDTO:
    """Validated NewsAPI article response entry."""

    source: NewsApiSourceDTO
    title: str
    published_at: str
    url: str
    author: str | None = None
    description: str | None = None
    url_to_image: str | None = None
    content: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, NewsApiSourceDTO):
            raise ValueError("source must be a NewsApiSourceDTO instance.")
        _require_text(self.title, "title")
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "published_at", _normalize_timestamp(self.published_at))
        object.__setattr__(self, "url", _normalize_url(self.url))
        object.__setattr__(self, "author", _optional_text(self.author))
        object.__setattr__(self, "description", _optional_text(self.description))
        object.__setattr__(self, "url_to_image", _optional_text(self.url_to_image))
        object.__setattr__(self, "content", _optional_text(self.content))


@dataclass(frozen=True, slots=True)
class NewsApiEverythingResponse:
    """Validated NewsAPI /v2/everything response."""

    status: str
    total_results: int
    articles: tuple[NewsApiArticleDTO, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status.strip().lower() != "ok":
            raise ValueError("status must be ok.")
        object.__setattr__(self, "status", "ok")
        if not isinstance(self.total_results, int) or self.total_results < 0:
            raise ValueError("total_results must be zero or positive.")
        if not isinstance(self.articles, tuple):
            raise ValueError("articles must be a tuple of NewsApiArticleDTO instances.")
        for article in self.articles:
            if not isinstance(article, NewsApiArticleDTO):
                raise ValueError("articles must contain NewsApiArticleDTO instances.")
