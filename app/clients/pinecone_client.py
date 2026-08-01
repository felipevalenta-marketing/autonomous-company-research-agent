"""Pinecone data-plane client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.clients.pinecone_dtos import (
    PineconeDeleteResultDTO,
    PineconeQueryMatchDTO,
    PineconeQueryResponseDTO,
    PineconeUpsertResultDTO,
    PineconeVectorRecordDTO,
)
from app.config.constants import PROJECT_NAME
from app.config.defaults import PineconeConfig
from app.models.execution import RuntimeConfig


class PineconeClientError(Exception):
    """Base exception for Pinecone failures."""


class PineconeConfigurationError(PineconeClientError):
    """Raised when Pinecone configuration is missing or invalid."""


class PineconeAuthenticationError(PineconeClientError):
    """Raised when Pinecone rejects the configured credentials."""


class PineconeTransportError(PineconeClientError):
    """Raised when Pinecone transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PineconeTimeoutError(PineconeTransportError):
    """Raised when Pinecone requests time out."""


class PineconeRateLimitError(PineconeTransportError):
    """Raised when Pinecone rate limiting is encountered."""


class PineconeResponseValidationError(PineconeClientError):
    """Raised when a Pinecone payload does not match the expected shape."""


class PineconePayloadError(PineconeResponseValidationError):
    """Raised when Pinecone returns a malformed successful payload."""


class PineconeClientProtocol(Protocol):
    """Minimal Pinecone client contract required by the services."""

    def upsert(self, records: Sequence[PineconeVectorRecordDTO], namespace: str) -> PineconeUpsertResultDTO:
        """Store prepared vector records."""

    def query(
        self,
        vector: Sequence[float],
        namespace: str,
        top_k: int,
        filter: Mapping[str, object] | None = None,
    ) -> PineconeQueryResponseDTO:
        """Query stored vectors."""

    def delete(
        self,
        namespace: str,
        ids: Sequence[str] | None = None,
        filter: Mapping[str, object] | None = None,
        delete_all: bool = False,
    ) -> PineconeDeleteResultDTO:
        """Delete stored vectors."""


class PineconeClient:
    """Synchronous Pinecone data-plane client."""

    def __init__(
        self,
        runtime_config: RuntimeConfig,
        pinecone_config: PineconeConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._runtime_config = runtime_config
        self._config = pinecone_config
        self._http_client = http_client or httpx.Client()

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._http_client.close()

    def upsert(self, records: Sequence[PineconeVectorRecordDTO], namespace: str) -> PineconeUpsertResultDTO:
        """Upsert prepared vector records into a namespace."""

        normalized_namespace = _normalize_namespace(namespace)
        normalized_records = tuple(records)
        if not normalized_records:
            raise PineconePayloadError("upsert requires at least one vector record.")
        _validate_record_dimensions(normalized_records, self._config.vector_dimension)

        body = {
            "vectors": [
                {
                    "id": record.record_id,
                    "values": list(record.values),
                    "metadata": record.metadata,
                }
                for record in normalized_records
            ],
            "namespace": normalized_namespace,
        }
        payload = self._request_json("/vectors/upsert", body)
        return _parse_upsert_response(payload, normalized_namespace)

    def query(
        self,
        vector: Sequence[float],
        namespace: str,
        top_k: int,
        filter: Mapping[str, object] | None = None,
    ) -> PineconeQueryResponseDTO:
        """Query vectors in a namespace."""

        normalized_namespace = _normalize_namespace(namespace)
        normalized_vector = _normalize_vector(vector)
        _validate_query_dimension(normalized_vector, self._config.vector_dimension)
        normalized_top_k = _normalize_positive_int(top_k, "top_k")
        normalized_filter = _normalize_filter(filter)

        body: dict[str, Any] = {
            "vector": list(normalized_vector),
            "topK": normalized_top_k,
            "namespace": normalized_namespace,
            "includeMetadata": True,
        }
        if normalized_filter is not None:
            body["filter"] = normalized_filter

        payload = self._request_json("/query", body)
        return _parse_query_response(payload, normalized_namespace)

    def delete(
        self,
        namespace: str,
        ids: Sequence[str] | None = None,
        filter: Mapping[str, object] | None = None,
        delete_all: bool = False,
    ) -> PineconeDeleteResultDTO:
        """Delete vectors from a namespace."""

        normalized_namespace = _normalize_namespace(namespace)
        delete_modes = sum((ids is not None, filter is not None, delete_all))
        if delete_modes != 1:
            raise PineconePayloadError("delete requires exactly one deletion mode.")

        body: dict[str, Any] = {"namespace": normalized_namespace}
        if delete_all:
            body["deleteAll"] = True
        elif ids is not None:
            normalized_ids = _normalize_nonempty_unique_texts(ids, "ids")
            body["ids"] = list(normalized_ids)
        else:
            normalized_filter = _normalize_filter(filter)
            if normalized_filter is None:
                raise PineconePayloadError("delete filter must not be empty.")
            body["filter"] = normalized_filter

        payload = self._request_json("/vectors/delete", body)
        return _parse_delete_response(payload, normalized_namespace)

    def _request_json(self, path: str, body: Mapping[str, Any]) -> Any:
        api_key = self._config.api_key
        if api_key is None or not api_key.strip():
            raise PineconeConfigurationError("PINECONE_API_KEY must be configured.")

        index_host = _normalize_index_host(self._config.index_host)
        headers = {
            "Api-Key": api_key.strip(),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
            "User-Agent": PROJECT_NAME,
        }
        if self._config.api_version and self._config.api_version.strip():
            headers["X-Pinecone-API-Version"] = self._config.api_version.strip()

        endpoint = f"{index_host}{path}"
        attempts = self._runtime_config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http_client.post(
                    endpoint,
                    json=dict(body),
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise PineconeTimeoutError("Pinecone request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise PineconeTransportError("Pinecone request failed.") from exc
                continue

            if response.status_code in {401, 403}:
                raise PineconeAuthenticationError("Pinecone rejected the configured credentials.")
            if response.status_code == 429:
                raise PineconeRateLimitError("Pinecone request was rate limited.", status_code=429)
            if 400 <= response.status_code < 500:
                raise PineconePayloadError("Pinecone request returned a client error status.")
            if response.status_code < 200 or response.status_code >= 300:
                raise PineconeTransportError(
                    "Pinecone request returned a non-success status.",
                    status_code=response.status_code,
                )

            payload = _decode_json(response)
            _raise_for_error_payload(payload)
            return payload

        raise PineconeTransportError("Pinecone request failed after retries.")


def _decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise PineconeResponseValidationError("Pinecone response was not valid JSON.") from exc


def _raise_for_error_payload(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        return

    error = payload.get("error")
    if error is None:
        return
    if isinstance(error, Mapping):
        message = str(error.get("message") or "Pinecone returned an error response.")
        error_type = str(error.get("type") or "").casefold()
        if "auth" in error_type or "permission" in error_type:
            raise PineconeAuthenticationError(message)
        if "rate" in error_type or "limit" in error_type:
            raise PineconeRateLimitError(message)
        raise PineconePayloadError(message)
    raise PineconePayloadError("Pinecone returned an error response.")


def _normalize_namespace(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PineconePayloadError("namespace must not be empty.")
    return value.strip()


def _normalize_index_host(value: str | None) -> str:
    if value is None or not value.strip():
        raise PineconeConfigurationError("PINECONE_INDEX_HOST must be configured.")
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise PineconeConfigurationError("PINECONE_INDEX_HOST must be an HTTPS URL.")
    return normalized


def _normalize_positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PineconePayloadError(f"{field_name} must be an integer.")
    if value <= 0:
        raise PineconePayloadError(f"{field_name} must be positive.")
    return value


def _validate_record_dimensions(records: tuple[PineconeVectorRecordDTO, ...], expected_dimension: int) -> None:
    normalized_expected = _normalize_positive_int(expected_dimension, "vector_dimension")
    dimensions = {len(record.values) for record in records}
    if len(dimensions) != 1:
        raise PineconePayloadError("upsert vectors must share the same dimension.")
    if dimensions.pop() != normalized_expected:
        raise PineconePayloadError("upsert vectors must match the configured index dimension.")


def _validate_query_dimension(vector: tuple[float, ...], expected_dimension: int) -> None:
    normalized_expected = _normalize_positive_int(expected_dimension, "vector_dimension")
    if len(vector) != normalized_expected:
        raise PineconePayloadError("query vector must match the configured index dimension.")


def _normalize_vector(vector: Sequence[float]) -> tuple[float, ...]:
    if isinstance(vector, str):
        raise PineconePayloadError("query vectors must be numeric collections.")
    normalized: list[float] = []
    for value in tuple(vector):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PineconePayloadError("query vectors must contain numeric values.")
        numeric = float(value)
        if not (numeric == numeric and numeric not in {float("inf"), float("-inf")}):
            raise PineconePayloadError("query vectors must contain finite values.")
        normalized.append(numeric)
    if not normalized:
        raise PineconePayloadError("query vectors must not be empty.")
    return tuple(normalized)


def _normalize_nonempty_unique_texts(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise PineconePayloadError(f"{field_name} must be an ordered collection of strings.")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PineconePayloadError(f"{field_name} must contain non-empty strings.")
        normalized_value = value.strip()
        if normalized_value in seen:
            raise PineconePayloadError(f"{field_name} must not contain duplicate values.")
        seen.add(normalized_value)
        normalized.append(normalized_value)
    if not normalized:
        raise PineconePayloadError(f"{field_name} must not be empty.")
    return tuple(normalized)


def _normalize_filter(filter_value: Mapping[str, object] | None) -> dict[str, object] | None:
    if filter_value is None:
        return None
    if not isinstance(filter_value, Mapping):
        raise PineconePayloadError("filter must be a mapping when provided.")

    normalized: dict[str, object] = {}
    for key, value in filter_value.items():
        if not isinstance(key, str) or not key.strip():
            raise PineconePayloadError("filter keys must be non-empty strings.")
        if value is None:
            raise PineconePayloadError("filter values must not be null.")
        if isinstance(value, Mapping):
            raise PineconePayloadError("filter values must be simple JSON-compatible values.")
        if isinstance(value, (list, tuple)):
            normalized[key.strip()] = _normalize_list(value)
            continue
        if isinstance(value, bool):
            normalized[key.strip()] = value
            continue
        if isinstance(value, int):
            normalized[key.strip()] = value
            continue
        if isinstance(value, float):
            if not (value == value and value not in {float("inf"), float("-inf")}):
                raise PineconePayloadError("filter numeric values must be finite.")
            normalized[key.strip()] = value
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise PineconePayloadError("filter string values must not be empty.")
            normalized[key.strip()] = stripped
            continue
        raise PineconePayloadError("filter values must be JSON-compatible.")
    if not normalized:
        raise PineconePayloadError("filter must not be empty.")
    return normalized


def _normalize_list(values: Sequence[object]) -> tuple[object, ...]:
    normalized: list[object] = []
    for value in values:
        if isinstance(value, Mapping):
            raise PineconePayloadError("filter lists must be flat.")
        if isinstance(value, (list, tuple)):
            raise PineconePayloadError("filter lists must not be nested.")
        if value is None:
            raise PineconePayloadError("filter lists must not contain null values.")
        if isinstance(value, bool):
            normalized.append(value)
        elif isinstance(value, int):
            normalized.append(value)
        elif isinstance(value, float):
            if not (value == value and value not in {float("inf"), float("-inf")}):
                raise PineconePayloadError("filter list numeric values must be finite.")
            normalized.append(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise PineconePayloadError("filter list string values must not be empty.")
            normalized.append(stripped)
        else:
            raise PineconePayloadError("filter list values must be JSON-compatible.")
    return tuple(normalized)


def _parse_upsert_response(payload: Any, namespace: str) -> PineconeUpsertResultDTO:
    if not isinstance(payload, Mapping):
        raise PineconeResponseValidationError("Pinecone upsert response must be a JSON object.")

    count = _extract_non_negative_int(payload, PineconePayloadError, "upsertedCount", "upserted_count")
    return PineconeUpsertResultDTO(namespace=namespace, upserted_count=count)


def _parse_delete_response(payload: Any, namespace: str) -> PineconeDeleteResultDTO:
    if not isinstance(payload, Mapping):
        raise PineconeResponseValidationError("Pinecone delete response must be a JSON object.")

    count = _extract_non_negative_int(payload, PineconePayloadError, "deletedCount", "deleted_count")
    return PineconeDeleteResultDTO(namespace=namespace, deleted_count=count)


def _parse_query_response(payload: Any, namespace: str) -> PineconeQueryResponseDTO:
    if not isinstance(payload, Mapping):
        raise PineconeResponseValidationError("Pinecone query response must be a JSON object.")

    matches_payload = payload.get("matches")
    if not isinstance(matches_payload, list):
        raise PineconeResponseValidationError("Pinecone query response requires a matches list.")

    matches = tuple(_parse_query_match(match) for match in matches_payload)
    response_namespace = payload.get("namespace")
    if response_namespace is None:
        response_namespace = namespace
    return PineconeQueryResponseDTO(matches=matches, namespace=response_namespace)


def _parse_query_match(payload: Any) -> PineconeQueryMatchDTO:
    if not isinstance(payload, Mapping):
        raise PineconeResponseValidationError("Pinecone query matches must be JSON objects.")

    record_id = payload.get("id")
    if not isinstance(record_id, str) or not record_id.strip():
        raise PineconeResponseValidationError("Pinecone query matches require a non-empty id.")
    score = payload.get("score")
    metadata = payload.get("metadata", {})
    values = payload.get("values")
    return PineconeQueryMatchDTO(
        record_id=record_id,
        score=score,
        metadata=metadata,
        values=tuple(values) if isinstance(values, list) else values,
    )


def _extract_non_negative_int(
    payload: Mapping[str, Any],
    error_type: type[PineconeResponseValidationError],
    *candidate_keys: str,
) -> int:
    for key in candidate_keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise error_type(f"{key} must be an integer.")
        if value < 0:
            raise error_type(f"{key} must be zero or positive.")
        return value
    raise error_type(f"Response must include one of: {', '.join(candidate_keys)}.")
