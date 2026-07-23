"""SEC client for deterministic SEC data retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from app.clients.sec_dtos import (
    SecCompanyFactsResponse,
    SecFactConcept,
    SecFactObservation,
    SecRecentFilingRecord,
    SecSubmissionsResponse,
    SecTickerRecord,
)
from app.config.constants import SEC_COMPANY_TICKERS_URL
from app.models.execution import RuntimeConfig
from app.utils.hashing import sha256_text


class SecClientError(Exception):
    """Base exception for SEC client failures."""


class SecConfigurationError(SecClientError):
    """Raised when SEC configuration is missing or invalid."""


class SecTransportError(SecClientError):
    """Raised when SEC transport or HTTP status handling fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SecTimeoutError(SecTransportError):
    """Raised when SEC requests time out."""


class SecRateLimitError(SecTransportError):
    """Raised when SEC rate limiting is encountered."""


class SecResponseValidationError(SecClientError):
    """Raised when the SEC payload does not match the expected shape."""


class SecSubmissionsPayloadError(SecResponseValidationError):
    """Raised when the SEC submissions payload is malformed."""


class SecRecentFilingArrayError(SecSubmissionsPayloadError):
    """Raised when recent-filing parallel arrays are malformed."""


class SecCompanyFactsPayloadError(SecResponseValidationError):
    """Raised when the SEC company-facts payload is malformed."""


class SecUnsupportedFactValueError(SecCompanyFactsPayloadError):
    """Raised when a company-facts observation value is unsupported."""


class SecNormalizationError(SecClientError):
    """Raised when SEC payload fields cannot be normalized safely."""


class SecClient:
    """Synchronous SEC client for the company ticker dataset."""

    def __init__(self, runtime_config: RuntimeConfig, http_client: httpx.Client | None = None) -> None:
        self._runtime_config = runtime_config
        self._http_client = http_client or httpx.Client()

    def get_company_tickers(self) -> tuple[SecTickerRecord, ...]:
        """Fetch validated company-ticker records from the SEC."""
        payload = self._fetch_json(SEC_COMPANY_TICKERS_URL)
        return _parse_company_ticker_payload(payload)

    def get_company_submissions(self, cik: int | str) -> SecSubmissionsResponse:
        """Fetch and validate a company's submissions payload."""

        normalized_cik = _normalize_cik(cik)
        url = f"https://data.sec.gov/submissions/CIK{normalized_cik}.json"
        payload = self._fetch_json(url)
        return _parse_company_submissions_payload(payload, normalized_cik)

    def get_company_facts(self, cik: int | str) -> SecCompanyFactsResponse:
        """Fetch and validate a company's SEC company-facts payload."""

        normalized_cik = _normalize_cik(cik)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized_cik}.json"
        payload = self._fetch_json(url)
        return _parse_company_facts_payload(payload, normalized_cik)

    def _fetch_json(self, url: str) -> Any:
        user_agent = self._runtime_config.sec_user_agent
        if user_agent is None or not user_agent.strip():
            raise SecConfigurationError("SEC_USER_AGENT must be configured.")

        headers = {
            "User-Agent": user_agent.strip(),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }

        attempts = self._runtime_config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http_client.get(
                    url,
                    headers=headers,
                    timeout=self._runtime_config.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise SecTimeoutError("SEC request timed out.") from exc
                continue
            except httpx.RequestError as exc:
                if attempt + 1 >= attempts:
                    raise SecTransportError("SEC request failed.") from exc
                continue

            if response.status_code == 429:
                raise SecRateLimitError("SEC request was rate limited.", status_code=response.status_code)
            if response.status_code < 200 or response.status_code >= 300:
                raise SecTransportError(
                    "SEC request returned a non-success status.",
                    status_code=response.status_code,
                )

            return self._decode_json(response)

        raise SecTransportError("SEC request failed after retries.")

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise SecResponseValidationError("SEC company ticker response was not valid JSON.") from exc


def _parse_company_ticker_payload(payload: Any) -> tuple[SecTickerRecord, ...]:
    if not isinstance(payload, Mapping):
        raise SecResponseValidationError("SEC company ticker response must be a JSON object.")

    records: list[SecTickerRecord] = []
    for key in sorted(payload, key=_payload_sort_key):
        entry = payload[key]
        if not isinstance(entry, Mapping):
            raise SecResponseValidationError("SEC company ticker entry must be a JSON object.")
        records.append(_parse_company_ticker_entry(entry))

    return tuple(records)


def _parse_company_submissions_payload(payload: Any, normalized_cik: str) -> SecSubmissionsResponse:
    if not isinstance(payload, Mapping):
        raise SecSubmissionsPayloadError("SEC submissions response must be a JSON object.")

    cik = _parse_cik(payload.get("cik"), SecSubmissionsPayloadError)
    if f"{cik:010d}" != normalized_cik:
        raise SecSubmissionsPayloadError("SEC submissions CIK did not match the requested company.")

    entity_name = _parse_text(payload.get("name"), "name", SecSubmissionsPayloadError)
    sic = _optional_text(payload.get("sic"))
    fiscal_year_end = _optional_text(payload.get("fiscalYearEnd"))
    tickers = _parse_text_sequence(payload.get("tickers"), "tickers", SecSubmissionsPayloadError)
    exchanges = _parse_text_sequence(payload.get("exchanges"), "exchanges", SecSubmissionsPayloadError)
    former_names = _parse_former_names(payload.get("formerNames"), SecSubmissionsPayloadError)
    recent_filings = _parse_recent_filings(payload.get("filings"))

    return SecSubmissionsResponse(
        cik=int(normalized_cik),
        entity_name=entity_name,
        sic=sic,
        fiscal_year_end=fiscal_year_end,
        tickers=tickers,
        exchanges=exchanges,
        former_names=former_names,
        recent_filings=recent_filings,
    )


def _parse_company_facts_payload(payload: Any, normalized_cik: str) -> SecCompanyFactsResponse:
    if not isinstance(payload, Mapping):
        raise SecCompanyFactsPayloadError("SEC company-facts response must be a JSON object.")

    cik = _parse_cik(payload.get("cik"), SecCompanyFactsPayloadError)
    if f"{cik:010d}" != normalized_cik:
        raise SecCompanyFactsPayloadError("SEC company-facts CIK did not match the requested company.")

    entity_name = _parse_text(payload.get("entityName"), "entityName", SecCompanyFactsPayloadError)
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise SecCompanyFactsPayloadError("SEC company-facts payload requires a facts object.")
    if not facts:
        raise SecCompanyFactsPayloadError("SEC company-facts payload requires at least one taxonomy.")

    concepts: list[SecFactConcept] = []
    for taxonomy, taxonomy_payload in facts.items():
        taxonomy_name = _parse_text(taxonomy, "taxonomy", SecCompanyFactsPayloadError)
        if not isinstance(taxonomy_payload, Mapping):
            raise SecCompanyFactsPayloadError("SEC taxonomy payload must be an object.")
        for concept_name, concept_payload in taxonomy_payload.items():
            concepts.append(_parse_fact_concept(taxonomy_name, concept_name, concept_payload))

    return SecCompanyFactsResponse(
        cik=int(normalized_cik),
        entity_name=entity_name,
        concepts=tuple(concepts),
    )


def _parse_fact_concept(taxonomy: str, concept_name: Any, concept_payload: Any) -> SecFactConcept:
    if not isinstance(concept_name, str) or not concept_name.strip():
        raise SecCompanyFactsPayloadError("SEC fact concept name must be a non-empty string.")
    if not isinstance(concept_payload, Mapping):
        raise SecCompanyFactsPayloadError("SEC fact concept payload must be an object.")

    label = _optional_text(concept_payload.get("label"))
    description = _optional_text(concept_payload.get("description"))
    units = concept_payload.get("units")
    if not isinstance(units, Mapping) or not units:
        raise SecCompanyFactsPayloadError("SEC fact concept requires a non-empty units object.")

    observations: list[SecFactObservation] = []
    for unit_name, unit_payload in units.items():
        unit = _parse_text(unit_name, "unit", SecCompanyFactsPayloadError)
        if not isinstance(unit_payload, list):
            raise SecCompanyFactsPayloadError("SEC fact unit payload must be a list.")
        for observation_payload in unit_payload:
            observations.append(_parse_fact_observation(unit, observation_payload))

    return SecFactConcept(
        taxonomy=taxonomy,
        concept=concept_name.strip(),
        observations=tuple(observations),
        label=label,
        description=description,
    )


def _parse_fact_observation(unit: str, observation_payload: Any) -> SecFactObservation:
    if not isinstance(observation_payload, Mapping):
        raise SecCompanyFactsPayloadError("SEC fact observation must be an object.")

    value = observation_payload.get("val")
    parsed_value = _parse_fact_value(value)
    accession_number = _parse_text(observation_payload.get("accn"), "accn", SecCompanyFactsPayloadError)
    form = _parse_text(observation_payload.get("form"), "form", SecCompanyFactsPayloadError)
    filed_date = _parse_text(observation_payload.get("filed"), "filed", SecCompanyFactsPayloadError)
    fiscal_year = _optional_int(observation_payload.get("fy"))
    fiscal_period = _optional_text(observation_payload.get("fp"))
    frame = _optional_text(observation_payload.get("frame"))
    start_date = _optional_text(observation_payload.get("start"))
    end_date = _optional_text(observation_payload.get("end"))

    return SecFactObservation(
        value=parsed_value,
        unit=unit,
        accession_number=accession_number,
        form=form,
        filed_date=filed_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        frame=frame,
        start_date=start_date,
        end_date=end_date,
    )


def _parse_recent_filings(filings_payload: Any) -> tuple[SecRecentFilingRecord, ...]:
    if not isinstance(filings_payload, Mapping):
        raise SecSubmissionsPayloadError("SEC submissions payload requires a filings object.")

    recent = filings_payload.get("recent")
    if not isinstance(recent, Mapping):
        raise SecSubmissionsPayloadError("SEC submissions payload requires a recent filings object.")

    accession_numbers = _require_sequence(recent.get("accessionNumber"), "accessionNumber")
    filing_dates = _require_sequence(recent.get("filingDate"), "filingDate")
    forms = _require_sequence(recent.get("form"), "form")
    primary_documents = _require_sequence(recent.get("primaryDocument"), "primaryDocument")

    record_count = len(accession_numbers)
    if not (len(filing_dates) == len(forms) == len(primary_documents) == record_count):
        raise SecRecentFilingArrayError("SEC submissions recent filing arrays must have compatible lengths.")

    report_dates = _optional_sequence(recent.get("reportDate"), record_count)
    acceptance_datetimes = _optional_sequence(recent.get("acceptanceDateTime"), record_count)
    file_numbers = _optional_sequence(recent.get("fileNumber"), record_count)
    descriptions = _optional_sequence(recent.get("primaryDocDescription"), record_count)

    records = []
    for index in range(record_count):
        records.append(
            SecRecentFilingRecord(
                accession_number=accession_numbers[index],
                filing_date=filing_dates[index],
                form=forms[index],
                primary_document=primary_documents[index],
                report_date=report_dates[index],
                acceptance_datetime=acceptance_datetimes[index],
                file_number=file_numbers[index],
                primary_doc_description=descriptions[index],
            )
        )
    return tuple(records)


def _parse_company_ticker_entry(entry: Mapping[str, Any]) -> SecTickerRecord:
    cik = _parse_cik(entry.get("cik_str"))
    ticker = _parse_text(entry.get("ticker"), "ticker")
    title = _parse_text(entry.get("title"), "title")
    return SecTickerRecord(cik=cik, ticker=ticker, title=title)


def _parse_cik(value: Any, error_type: type[Exception] = SecResponseValidationError) -> int:
    if isinstance(value, int):
        cik = value
    elif isinstance(value, str) and value.strip().isdigit():
        cik = int(value.strip())
    else:
        raise error_type("SEC payload requires a numeric CIK value.")

    if cik <= 0:
        raise error_type("SEC payload CIK must be positive.")
    return cik


def _parse_text(value: Any, field_name: str, error_type: type[Exception] = SecResponseValidationError) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"SEC payload requires a non-empty {field_name} value.")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise SecCompanyFactsPayloadError("SEC observation integer field must be numeric when provided.")


def _parse_fact_value(value: Any) -> int | float | str:
    if isinstance(value, (int, float, str)):
        return value
    raise SecUnsupportedFactValueError("SEC fact observation value must be numeric or text.")


def _parse_text_sequence(
    value: Any,
    field_name: str,
    error_type: type[Exception] = SecSubmissionsPayloadError,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise error_type(f"SEC submissions field {field_name} must be a list when provided.")
    result = []
    for item in value:
        result.append(_parse_text(item, field_name, error_type))
    return tuple(result)


def _parse_former_names(value: Any, error_type: type[Exception] = SecSubmissionsPayloadError) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise error_type("SEC formerNames field must be a list when provided.")
    result = []
    for item in value:
        if isinstance(item, Mapping):
            name = item.get("name")
            result.append(_parse_text(name, "formerNames.name", error_type))
        else:
            result.append(_parse_text(item, "formerNames", error_type))
    return tuple(result)


def _require_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SecSubmissionsPayloadError(f"SEC submissions field {field_name} is required and must be a list.")
    return tuple(_parse_text(item, field_name) for item in value)


def _optional_sequence(value: Any, expected_length: int) -> tuple[str | None, ...]:
    if value is None:
        return tuple(None for _ in range(expected_length))
    if not isinstance(value, list):
        raise SecRecentFilingArrayError("SEC submissions optional recent filing arrays must be lists when provided.")
    if len(value) != expected_length:
        raise SecRecentFilingArrayError("SEC submissions recent filing arrays must have compatible lengths.")
    return tuple(_optional_text(item) for item in value)


def _normalize_cik(cik: int | str) -> str:
    if isinstance(cik, int):
        normalized = cik
    elif isinstance(cik, str) and cik.strip().isdigit():
        normalized = int(cik.strip())
    else:
        raise SecNormalizationError("CIK must be numeric.")
    if normalized <= 0:
        raise SecNormalizationError("CIK must be positive.")
    return f"{normalized:010d}"


def build_sec_submission_url(cik: int | str, accession_number: str, primary_document: str) -> str:
    """Construct a deterministic SEC archive URL for a filing."""

    normalized_cik = _normalize_cik(cik)
    if not isinstance(accession_number, str) or not accession_number.strip():
        raise SecNormalizationError("Accession number must be a non-empty string.")
    accession_number = accession_number.strip()
    accession_fragment = accession_number.replace("-", "")
    if not accession_fragment.isdigit():
        raise SecNormalizationError("Accession number must contain digits and hyphens only.")
    if not isinstance(primary_document, str) or not primary_document.strip():
        raise SecNormalizationError("Primary document must be a non-empty string.")
    primary_document = primary_document.strip()
    if any(separator in primary_document for separator in ("/", "\\", "..")):
        raise SecNormalizationError("Primary document name is unsafe.")
    encoded_document = quote(primary_document, safe="._-")
    archive_cik = str(int(normalized_cik))
    return f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession_fragment}/{encoded_document}"


def build_sec_source_identity(
    cik: int | str,
    accession_number: str,
    primary_document: str,
    form: str,
) -> tuple[str, str]:
    """Return deterministic source and document identifiers for SEC filings."""

    normalized_cik = _normalize_cik(cik)
    accession_fragment = accession_number.replace("-", "")
    archive_key = f"{normalized_cik}:{accession_fragment}:{primary_document.strip()}:{form.strip()}"
    digest = sha256_text(archive_key)[:16]
    source_id = f"sec_source_{digest}"
    document_id = f"sec_document_{digest}"
    return source_id, document_id


def _payload_sort_key(key: Any) -> tuple[int, str]:
    text = str(key)
    if text.isdigit():
        return (0, f"{int(text):020d}")
    return (1, text)
