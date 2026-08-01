"""OpenAI embeddings client for deterministic vector generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app.clients.openai_embedding_dtos import (
    OpenAIEmbeddingItemDTO,
    OpenAIEmbeddingUsageDTO,
    OpenAIEmbeddingsResponseDTO,
)
from app.config.constants import OPENAI_BASE_URL, OPENAI_DEFAULT_EMBEDDING_MODEL, PROJECT_NAME
from app.models.execution import RuntimeConfig


class OpenAIEmbeddingsClientError(Exception):
    """Base exception for OpenAI embeddings failures."""


class OpenAIEmbeddingsConfigurationError(OpenAIEmbeddingsClientError):
    """Raised when OpenAI embeddings configuration is missing or invalid."""


class OpenAIEmbeddingsAuthenticationError(OpenAIEmbeddingsClientError):
    """Raised when OpenAI rejects the configured credentials."""


class OpenAIEmbeddingsTransportError(OpenAIEmbeddingsClientError):
    """Raised when OpenAI transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenAIEmbeddingsTimeoutError(OpenAIEmbeddingsTransportError):
    """Raised when OpenAI embeddings requests time out."""


class OpenAIEmbeddingsRateLimitError(OpenAIEmbeddingsTransportError):
    """Raised when OpenAI embeddings rate limiting is encountered."""


class OpenAIEmbeddingsResponseValidationError(OpenAIEmbeddingsClientError):
    """Raised when an OpenAI embeddings payload does not match the expected shape."""


class OpenAIEmbeddingsPayloadError(OpenAIEmbeddingsResponseValidationError):
    """Raised when OpenAI returns a malformed successful payload."""


class OpenAIEmbeddingsClient:
    """Synchronous OpenAI embeddings client."""

    def __init__(
        self,
        runtime_config: RuntimeConfig,
        http_client: httpx.Client | None = None,
        *,
        base_url: str = OPENAI_BASE_URL,
        default_model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self._runtime_config = runtime_config
        self._http_client = http_client or httpx.Client()
        self._base_url = _normalize_base_url(base_url)
        self._default_model = _normalize_model(default_model)

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._http_client.close()

    def create_embeddings(
        self,
        texts: str | Sequence[str],
        model: str | None = None,
        dimensions: int | None = None,
    ) -> OpenAIEmbeddingsResponseDTO:
        """Create validated OpenAI embedding DTOs for the given texts."""

        normalized_texts = _normalize_texts(texts)
        normalized_model = _normalize_model(model or self._default_model)
        normalized_dimensions = _normalize_dimensions(dimensions)
        payload = self._fetch_json(normalized_texts, normalized_model, normalized_dimensions)
        try:
            return _parse_embeddings_response(payload, normalized_model)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise OpenAIEmbeddingsResponseValidationError("OpenAI embeddings response could not be validated.") from exc

    def _fetch_json(
        self,
        texts: tuple[str, ...],
        model: str,
        dimensions: int | None,
    ) -> Any:
        api_key = self._runtime_config.openai_api_key
        if api_key is None or not api_key.strip():
            raise OpenAIEmbeddingsConfigurationError("OPENAI_API_KEY must be configured.")

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": PROJECT_NAME,
        }
        body: dict[str, Any] = {
            "model": model,
            "input": list(texts),
        }
        if dimensions is not None:
            body["dimensions"] = dimensions

        attempts = self._runtime_config.max_retries + 1
        endpoint = f"{self._base_url}/embeddings"
        for attempt in range(attempts):
            try:
                response = self._http_client.post(
                    endpoint,
                    json=body,
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise OpenAIEmbeddingsTimeoutError("OpenAI embeddings request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise OpenAIEmbeddingsTransportError("OpenAI embeddings request failed.") from exc
                continue

            if response.status_code in {401, 403}:
                raise OpenAIEmbeddingsAuthenticationError("OpenAI rejected the configured credentials.")
            if response.status_code == 429:
                raise OpenAIEmbeddingsRateLimitError("OpenAI embeddings request was rate limited.", status_code=429)
            if response.status_code == 400:
                raise OpenAIEmbeddingsPayloadError("OpenAI embeddings request returned a bad request status.")
            if response.status_code < 200 or response.status_code >= 300:
                raise OpenAIEmbeddingsTransportError(
                    "OpenAI embeddings request returned a non-success status.",
                    status_code=response.status_code,
                )

            payload = self._decode_json(response)
            _raise_for_error_payload(payload)
            return payload

        raise OpenAIEmbeddingsTransportError("OpenAI embeddings request failed after retries.")

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise OpenAIEmbeddingsResponseValidationError("OpenAI embeddings response was not valid JSON.") from exc


def _parse_embeddings_response(payload: Any, requested_model: str) -> OpenAIEmbeddingsResponseDTO:
    if not isinstance(payload, Mapping):
        raise OpenAIEmbeddingsResponseValidationError("OpenAI embeddings response must be a JSON object.")

    response_model = _require_text(payload.get("model"), "model")
    if response_model != requested_model:
        raise OpenAIEmbeddingsPayloadError("OpenAI embeddings response model did not match the request.")

    data_payload = payload.get("data")
    if not isinstance(data_payload, list):
        raise OpenAIEmbeddingsResponseValidationError("OpenAI embeddings response requires a data list.")

    usage_payload = payload.get("usage")
    if not isinstance(usage_payload, Mapping):
        raise OpenAIEmbeddingsResponseValidationError("OpenAI embeddings response requires a usage object.")

    try:
        items = tuple(_parse_item(item) for item in data_payload)
        usage = _parse_usage(usage_payload)
        return OpenAIEmbeddingsResponseDTO(model=response_model, data=items, usage=usage)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise OpenAIEmbeddingsPayloadError("OpenAI embeddings payload was malformed.") from exc


def _parse_item(payload: Any) -> OpenAIEmbeddingItemDTO:
    if not isinstance(payload, Mapping):
        raise OpenAIEmbeddingsResponseValidationError("OpenAI embedding item must be a JSON object.")

    try:
        index = _require_non_negative_int(payload.get("index"), "index")
        embedding_payload = payload.get("embedding")
        if not isinstance(embedding_payload, (list, tuple)):
            raise OpenAIEmbeddingsResponseValidationError("OpenAI embedding item requires an embedding list.")
        embedding = tuple(embedding_payload)
        return OpenAIEmbeddingItemDTO(index=index, embedding=embedding)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise OpenAIEmbeddingsPayloadError("OpenAI embedding item was malformed.") from exc


def _parse_usage(payload: Mapping[str, Any]) -> OpenAIEmbeddingUsageDTO:
    try:
        prompt_tokens = _require_non_negative_int(payload.get("prompt_tokens"), "prompt_tokens")
        total_tokens = _require_non_negative_int(payload.get("total_tokens"), "total_tokens")
        return OpenAIEmbeddingUsageDTO(prompt_tokens=prompt_tokens, total_tokens=total_tokens)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise OpenAIEmbeddingsPayloadError("OpenAI embeddings usage metadata was malformed.") from exc


def _raise_for_error_payload(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        return

    error = payload.get("error")
    if not isinstance(error, Mapping):
        return

    error_type = _optional_text(error.get("type"))
    message = "OpenAI returned an error response."
    lowered = (error_type or "").casefold()
    if "auth" in lowered or "key" in lowered or "permission" in lowered:
        raise OpenAIEmbeddingsAuthenticationError(message)
    if "rate" in lowered or "limit" in lowered or "quota" in lowered:
        raise OpenAIEmbeddingsRateLimitError(message)
    if "request" in lowered or "invalid" in lowered or "parameter" in lowered:
        raise OpenAIEmbeddingsPayloadError(message)
    raise OpenAIEmbeddingsPayloadError(message)


def _normalize_texts(texts: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(texts, str):
        normalized = (texts,)
    else:
        try:
            normalized = tuple(texts)
        except TypeError as exc:
            raise OpenAIEmbeddingsPayloadError("input must be a string or an ordered collection of strings.") from exc

    if not normalized:
        raise OpenAIEmbeddingsPayloadError("input must not be empty.")

    result: list[str] = []
    for text in normalized:
        if not isinstance(text, str):
            raise OpenAIEmbeddingsPayloadError("input must contain only strings.")
        if not text.strip():
            raise OpenAIEmbeddingsPayloadError("input must not contain blank strings.")
        result.append(text)
    return tuple(result)


def _normalize_model(value: str) -> str:
    try:
        return _require_text(value, "model")
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise OpenAIEmbeddingsConfigurationError("model must be configured.") from exc


def _normalize_base_url(value: str) -> str:
    try:
        base_url = _require_text(value, "base_url")
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise OpenAIEmbeddingsConfigurationError("base_url must be configured.") from exc
    return base_url.rstrip("/")


def _normalize_dimensions(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenAIEmbeddingsPayloadError("dimensions must be an integer when provided.")
    if value <= 0:
        raise OpenAIEmbeddingsPayloadError("dimensions must be positive when provided.")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenAIEmbeddingsResponseValidationError(f"OpenAI embeddings response requires a non-empty {field_name} value.")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenAIEmbeddingsResponseValidationError(f"OpenAI embeddings response requires a numeric {field_name} value.")
    if value < 0:
        raise OpenAIEmbeddingsResponseValidationError(f"OpenAI embeddings response requires a zero or positive {field_name} value.")
    return value
