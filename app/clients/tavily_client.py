"""Tavily client for deterministic market-research retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

import httpx

from app.clients.tavily_dtos import TavilySearchResponse, TavilySearchResultDTO
from app.config.constants import (
    PROJECT_NAME,
    TAVILY_BASE_URL,
    TAVILY_DEFAULT_LOOKBACK_DAYS,
    TAVILY_DEFAULT_MAX_RESULTS,
    TAVILY_DEFAULT_TOPIC,
    TAVILY_MAX_LOOKBACK_DAYS,
    TAVILY_MAX_RESULTS,
    TAVILY_SEARCH_URL,
)
from app.models.execution import RuntimeConfig


class TavilyClientError(Exception):
    """Base exception for Tavily client failures."""


class TavilyConfigurationError(TavilyClientError):
    """Raised when Tavily configuration is missing or invalid."""


class TavilyAuthenticationError(TavilyClientError):
    """Raised when Tavily rejects the configured credentials."""


class TavilyTransportError(TavilyClientError):
    """Raised when Tavily transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TavilyTimeoutError(TavilyTransportError):
    """Raised when Tavily requests time out."""


class TavilyRateLimitError(TavilyTransportError):
    """Raised when Tavily rate limiting is encountered."""


class TavilyResponseValidationError(TavilyClientError):
    """Raised when a Tavily payload does not match the expected shape."""


class TavilyPayloadError(TavilyResponseValidationError):
    """Raised when Tavily returns a malformed successful payload."""


class TavilyClient:
    """Synchronous Tavily client for the `/search` endpoint."""

    def __init__(self, runtime_config: RuntimeConfig, http_client: httpx.Client | None = None) -> None:
        self._runtime_config = runtime_config
        self._http_client = http_client or httpx.Client()

    def search(
        self,
        query: str,
        *,
        topic: str = TAVILY_DEFAULT_TOPIC,
        max_results: int = TAVILY_DEFAULT_MAX_RESULTS,
        include_answer: bool = False,
        include_raw_content: bool = False,
        days: int | None = TAVILY_DEFAULT_LOOKBACK_DAYS,
    ) -> TavilySearchResponse:
        """Search Tavily and return validated DTOs."""

        payload = self._fetch_json(
            query=query,
            topic=topic,
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            days=days,
        )
        return _parse_search_response(payload)

    def _fetch_json(
        self,
        *,
        query: str,
        topic: str,
        max_results: int,
        include_answer: bool,
        include_raw_content: bool,
        days: int | None,
    ) -> Any:
        api_key = self._runtime_config.tavily_api_key
        if api_key is None or not api_key.strip():
            raise TavilyConfigurationError("TAVILY_API_KEY must be configured.")

        body: dict[str, Any] = {
            "query": _normalize_query(query),
            "topic": _normalize_topic(topic),
            "max_results": _normalize_max_results(max_results),
            "include_answer": bool(include_answer),
            "include_raw_content": bool(include_raw_content),
        }
        if days is not None:
            body["days"] = _normalize_days(days)

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": PROJECT_NAME,
        }

        attempts = self._runtime_config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http_client.post(
                    TAVILY_SEARCH_URL,
                    json=body,
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise TavilyTimeoutError("Tavily request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise TavilyTransportError("Tavily request failed.") from exc
                continue

            if response.status_code in {401, 403}:
                raise TavilyAuthenticationError("Tavily rejected the configured credentials.")
            if response.status_code == 429:
                raise TavilyRateLimitError("Tavily request was rate limited.", status_code=429)
            if response.status_code < 200 or response.status_code >= 300:
                raise TavilyTransportError("Tavily request returned a non-success status.", status_code=response.status_code)

            payload = self._decode_json(response)
            _raise_for_error_payload(payload)
            return payload

        raise TavilyTransportError("Tavily request failed after retries.")

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise TavilyResponseValidationError("Tavily response was not valid JSON.") from exc


def _parse_search_response(payload: Any) -> TavilySearchResponse:
    if not isinstance(payload, Mapping):
        raise TavilyResponseValidationError("Tavily response must be a JSON object.")

    query = _require_text(payload.get("query"), "query")
    answer = _optional_text(payload.get("answer"))
    response_time = _optional_float(payload.get("response_time"))
    request_id = _optional_text(payload.get("request_id"))

    results_payload = payload.get("results")
    if not isinstance(results_payload, list):
        raise TavilyResponseValidationError("Tavily response requires a results list.")

    results = tuple(_parse_result(result) for result in results_payload)
    return TavilySearchResponse(
        query=query,
        answer=answer,
        results=results,
        response_time=response_time,
        request_id=request_id,
    )


def _parse_result(payload: Any) -> TavilySearchResultDTO:
    if not isinstance(payload, Mapping):
        raise TavilyResponseValidationError("Tavily search result must be a JSON object.")

    return TavilySearchResultDTO(
        title=_require_text(payload.get("title"), "title"),
        url=_require_text(payload.get("url"), "url"),
        content=_optional_text(payload.get("content")),
        score=_optional_float(payload.get("score")),
        published_date=_optional_published_date(payload.get("published_date")),
    )


def _raise_for_error_payload(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        return

    status = payload.get("status")
    if not isinstance(status, str) or status.strip().lower() != "error":
        return

    message = _optional_text(payload.get("message")) or "Tavily returned an error response."
    detail = _optional_text(payload.get("detail"))
    lowered = (message + " " + (detail or "")).casefold()
    if "api key" in lowered or "unauthorized" in lowered or "auth" in lowered:
        raise TavilyAuthenticationError(message)
    if "rate" in lowered or "limit" in lowered:
        raise TavilyRateLimitError(message)
    raise TavilyPayloadError(message)


def _normalize_query(value: str) -> str:
    return _require_text(value, "query")


def _normalize_topic(value: str) -> str:
    text = _require_text(value, "topic")
    return text.strip().lower()


def _normalize_max_results(value: int) -> int:
    if not isinstance(value, int):
        raise TavilyPayloadError("max_results must be an integer.")
    if value <= 0:
        raise TavilyPayloadError("max_results must be positive.")
    return min(value, TAVILY_MAX_RESULTS)


def _normalize_days(value: int) -> int:
    if not isinstance(value, int):
        raise TavilyPayloadError("days must be an integer.")
    if value <= 0:
        raise TavilyPayloadError("days must be positive.")
    return min(value, TAVILY_MAX_LOOKBACK_DAYS)


def _require_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise TavilyResponseValidationError(f"Tavily response requires a non-empty {field_name} value.")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise TavilyResponseValidationError("Tavily numeric field must not be empty when provided.")
        try:
            score = float(stripped)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise TavilyResponseValidationError("Tavily numeric field must be numeric when provided.") from exc
    else:
        raise TavilyResponseValidationError("Tavily numeric field must be numeric when provided.")
    if not isfinite(score):
        raise TavilyResponseValidationError("Tavily numeric field must be finite when provided.")
    if score < 0:
        raise TavilyResponseValidationError("Tavily numeric field must be zero or positive.")
    return score


def _optional_published_date(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TavilyResponseValidationError("published_date must be a string when provided.")
    stripped = value.strip()
    if not stripped:
        raise TavilyResponseValidationError("published_date must not be empty when provided.")
    if "T" in stripped:
        from datetime import UTC, datetime

        parsed_value = stripped.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(parsed_value)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise TavilyResponseValidationError("published_date must be a valid ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            raise TavilyResponseValidationError("published_date must include timezone information.")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        from datetime import date

        date.fromisoformat(stripped)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise TavilyResponseValidationError("published_date must be a valid ISO-8601 date or timestamp.") from exc
    return stripped
