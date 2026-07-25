"""NewsAPI client for deterministic news retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.clients.newsapi_dtos import NewsApiArticleDTO, NewsApiEverythingResponse, NewsApiSourceDTO
from app.config.constants import (
    NEWS_API_DEFAULT_LANGUAGE,
    NEWS_API_DEFAULT_PAGE_SIZE,
    NEWS_API_DEFAULT_SORT_BY,
    NEWS_API_EVERYTHING_URL,
    NEWS_API_MAX_PAGE_SIZE,
    PROJECT_NAME,
)
from app.models.execution import RuntimeConfig


class NewsApiClientError(Exception):
    """Base exception for NewsAPI client failures."""


class NewsApiConfigurationError(NewsApiClientError):
    """Raised when NewsAPI configuration is missing or invalid."""


class NewsApiAuthenticationError(NewsApiClientError):
    """Raised when NewsAPI rejects the configured credentials."""


class NewsApiTransportError(NewsApiClientError):
    """Raised when NewsAPI transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NewsApiTimeoutError(NewsApiTransportError):
    """Raised when NewsAPI requests time out."""


class NewsApiRateLimitError(NewsApiTransportError):
    """Raised when NewsAPI rate limiting is encountered."""


class NewsApiResponseValidationError(NewsApiClientError):
    """Raised when a NewsAPI payload does not match the expected shape."""


class NewsApiPayloadError(NewsApiResponseValidationError):
    """Raised when NewsAPI reports an invalid request or error payload."""


class NewsApiClient:
    """Synchronous NewsAPI client for the `/v2/everything` endpoint."""

    def __init__(self, runtime_config: RuntimeConfig, http_client: httpx.Client | None = None) -> None:
        self._runtime_config = runtime_config
        self._http_client = http_client or httpx.Client()

    def search_everything(
        self,
        query: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str = NEWS_API_DEFAULT_LANGUAGE,
        sort_by: str = NEWS_API_DEFAULT_SORT_BY,
        page_size: int = NEWS_API_DEFAULT_PAGE_SIZE,
        page: int = 1,
    ) -> NewsApiEverythingResponse:
        """Search the NewsAPI everything endpoint and return validated DTOs."""

        payload = self._fetch_json(
            query=query,
            from_date=from_date,
            to_date=to_date,
            language=language,
            sort_by=sort_by,
            page_size=page_size,
            page=page,
        )
        return _parse_everything_response(payload)

    def _fetch_json(
        self,
        *,
        query: str,
        from_date: str | None,
        to_date: str | None,
        language: str,
        sort_by: str,
        page_size: int,
        page: int,
    ) -> Any:
        api_key = self._runtime_config.news_api_key
        if api_key is None or not api_key.strip():
            raise NewsApiConfigurationError("NEWS_API_KEY must be configured.")

        normalized_query = _normalize_query(query)
        normalized_page_size = _normalize_page_size(page_size)
        normalized_page = _normalize_positive_int(page, "page")
        headers = {
            "X-Api-Key": api_key.strip(),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": PROJECT_NAME,
        }
        params: dict[str, Any] = {
            "q": normalized_query,
            "language": _normalize_optional_text(language) or NEWS_API_DEFAULT_LANGUAGE,
            "sortBy": _normalize_optional_text(sort_by) or NEWS_API_DEFAULT_SORT_BY,
            "pageSize": normalized_page_size,
            "page": normalized_page,
        }
        if from_date is not None:
            params["from"] = _normalize_optional_text(from_date)
        if to_date is not None:
            params["to"] = _normalize_optional_text(to_date)

        attempts = self._runtime_config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http_client.get(
                    NEWS_API_EVERYTHING_URL,
                    params=params,
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise NewsApiTimeoutError("NewsAPI request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise NewsApiTransportError("NewsAPI request failed.") from exc
                continue

            if response.status_code == 401:
                raise NewsApiAuthenticationError("NewsAPI rejected the configured credentials.")
            if response.status_code == 429:
                raise NewsApiRateLimitError("NewsAPI request was rate limited.", status_code=429)
            if response.status_code == 400:
                raise NewsApiPayloadError("NewsAPI request returned a bad request status.")
            if response.status_code < 200 or response.status_code >= 300:
                raise NewsApiTransportError(
                    "NewsAPI request returned a non-success status.",
                    status_code=response.status_code,
                )

            payload = self._decode_json(response)
            _raise_for_error_payload(payload)
            return payload

        raise NewsApiTransportError("NewsAPI request failed after retries.")

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise NewsApiResponseValidationError("NewsAPI response was not valid JSON.") from exc


def _parse_everything_response(payload: Any) -> NewsApiEverythingResponse:
    if not isinstance(payload, Mapping):
        raise NewsApiResponseValidationError("NewsAPI response must be a JSON object.")

    status = _normalize_optional_text(payload.get("status"))
    if status is None:
        raise NewsApiResponseValidationError("NewsAPI response requires a status value.")
    if status.lower() != "ok":
        raise NewsApiPayloadError("NewsAPI returned an error status.")

    total_results = _parse_non_negative_int(payload.get("totalResults"), "totalResults")
    articles_payload = payload.get("articles")
    if not isinstance(articles_payload, list):
        raise NewsApiResponseValidationError("NewsAPI response requires an articles list.")

    articles = tuple(_parse_article(article) for article in articles_payload)
    return NewsApiEverythingResponse(status="ok", total_results=total_results, articles=articles)


def _parse_article(payload: Any) -> NewsApiArticleDTO:
    if not isinstance(payload, Mapping):
        raise NewsApiResponseValidationError("NewsAPI article must be a JSON object.")

    source_payload = payload.get("source")
    if not isinstance(source_payload, Mapping):
        raise NewsApiResponseValidationError("NewsAPI article requires a source object.")

    return NewsApiArticleDTO(
        source=NewsApiSourceDTO(
            id=_normalize_optional_text(source_payload.get("id")),
            name=_require_text(source_payload.get("name"), "source.name"),
        ),
        author=_normalize_optional_text(payload.get("author")),
        title=_require_text(payload.get("title"), "title"),
        description=_normalize_optional_text(payload.get("description")),
        url=_require_text(payload.get("url"), "url"),
        url_to_image=_normalize_optional_text(payload.get("urlToImage")),
        published_at=_require_text(payload.get("publishedAt"), "publishedAt"),
        content=_normalize_optional_text(payload.get("content")),
    )


def _raise_for_error_payload(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        return

    status = payload.get("status")
    if not isinstance(status, str) or status.strip().lower() != "error":
        return

    code = _normalize_optional_text(payload.get("code"))
    message = _normalize_optional_text(payload.get("message")) or "NewsAPI returned an error response."
    if code is not None:
        lowered = code.casefold()
        if "api" in lowered and "key" in lowered:
            raise NewsApiAuthenticationError(message)
        if "rate" in lowered or "limit" in lowered:
            raise NewsApiRateLimitError(message)
        if "parameter" in lowered or "request" in lowered or "invalid" in lowered:
            raise NewsApiPayloadError(message)
    raise NewsApiPayloadError(message)


def _normalize_query(value: str) -> str:
    if not isinstance(value, str):
        raise NewsApiPayloadError("NewsAPI query must be a non-empty string.")
    text = value.strip()
    if not text:
        raise NewsApiPayloadError("NewsAPI query must not be empty.")
    return text


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _require_text(value: Any, field_name: str) -> str:
    text = _normalize_optional_text(value)
    if text is None:
        raise NewsApiResponseValidationError(f"NewsAPI article requires a non-empty {field_name} value.")
    return text


def _parse_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise NewsApiResponseValidationError(f"NewsAPI response requires a numeric {field_name} value.")
    if result < 0:
        raise NewsApiResponseValidationError(f"NewsAPI response requires a zero or positive {field_name} value.")
    return result


def _normalize_page_size(value: int) -> int:
    if value <= 0:
        raise NewsApiPayloadError("NewsAPI pageSize must be positive.")
    return min(value, NEWS_API_MAX_PAGE_SIZE)


def _normalize_positive_int(value: int, field_name: str) -> int:
    if value <= 0:
        raise NewsApiPayloadError(f"NewsAPI {field_name} must be positive.")
    return value
