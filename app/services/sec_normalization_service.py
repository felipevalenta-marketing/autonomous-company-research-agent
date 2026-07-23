"""SEC normalization helpers for canonical model conversion.

The company-facts path is implemented early for the next SEC stage but remains
inactive from the current entrypoint and workflow.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.clients.sec_client import (
    SecNormalizationError,
    build_sec_source_identity,
    build_sec_submission_url,
)
from app.clients.sec_dtos import SecCompanyFactsResponse, SecFactObservation, SecSubmissionsResponse
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.models.execution import RuntimeConfig
from app.models.providers import FinancialMetric
from app.models.sources import SourceRecord
from app.utils.hashing import sha256_text

SUPPORTED_SEC_FORMS = {"10-K", "10-Q", "8-K"}

ALLOWED_SEC_FACT_CONCEPTS = {
    "us-gaap": {
        "Assets": "Assets",
        "CashAndCashEquivalentsAtCarryingValue": "Cash and Cash Equivalents",
        "Liabilities": "Liabilities",
        "NetIncomeLoss": "Net Income",
        "OperatingIncomeLoss": "Operating Income",
        "Revenues": "Revenue",
        "StockholdersEquity": "Stockholders Equity",
    }
}


def normalize_sec_submissions(
    company: ResolvedCompany,
    submissions: SecSubmissionsResponse,
    runtime_config: RuntimeConfig | None = None,
) -> tuple[list[DocumentRecord], list[SourceRecord]]:
    """Convert SEC submissions metadata into canonical document and source records."""

    del runtime_config

    documents: list[DocumentRecord] = []
    sources: list[SourceRecord] = []
    seen_accessions: set[str] = set()

    for filing in submissions.recent_filings:
        if filing.form not in SUPPORTED_SEC_FORMS:
            continue
        if filing.accession_number in seen_accessions:
            continue
        seen_accessions.add(filing.accession_number)

        source_id, document_id = build_sec_source_identity(
            company.cik or submissions.cik,
            filing.accession_number,
            filing.primary_document,
            filing.form,
        )
        source_url = build_sec_submission_url(company.cik or submissions.cik, filing.accession_number, filing.primary_document)

        documents.append(
            DocumentRecord(
                document_id=document_id,
                company_name=company.company_name,
                source_id=source_id,
                document_type="sec_filing",
                title=f"{filing.form} filing",
                source_url=source_url,
                filing_type=filing.form,
                filing_date=filing.filing_date,
                fiscal_period=filing.report_date,
            )
        )
        sources.append(
            SourceRecord(
                source_id=source_id,
                company_name=company.company_name,
                provider_name="SEC EDGAR",
                authority_level="primary",
                acquired_at=filing.acceptance_datetime or filing.filing_date,
                source_url=source_url,
                raw_reference=filing.accession_number,
                document_id=document_id,
                payload_type="submissions",
            )
        )

    return documents, sources


def normalize_sec_company_facts(
    company: ResolvedCompany,
    facts: SecCompanyFactsResponse,
    runtime_config: RuntimeConfig | None = None,
) -> list[FinancialMetric]:
    """Convert SEC company-facts observations into canonical financial metrics."""

    del runtime_config

    metrics: list[FinancialMetric] = []
    seen_keys: set[str] = set()

    for concept in facts.concepts:
        metric_name = ALLOWED_SEC_FACT_CONCEPTS.get(concept.taxonomy, {}).get(concept.concept)
        if metric_name is None:
            continue
        for observation in _select_observations(concept.observations):
            if not isinstance(observation.value, (int, float)):
                raise SecNormalizationError("SEC fact observation value must be numeric for financial metrics.")
            metric_key = _metric_identity_key(company, concept.taxonomy, concept.concept, observation)
            if metric_key in seen_keys:
                continue
            seen_keys.add(metric_key)

            metrics.append(
                FinancialMetric(
                    metric_id=f"sec_metric_{sha256_text(metric_key)[:16]}",
                    company_name=company.company_name,
                    metric_name=metric_name,
                    value=float(observation.value),
                    period=_build_metric_period(observation),
                    source_id=f"sec_fact_source_{sha256_text(metric_key)[:16]}",
                    unit=observation.unit,
                    currency=observation.unit if observation.unit.upper() == "USD" else None,
                )
            )

    return metrics


def _metric_identity_key(
    company: ResolvedCompany,
    taxonomy: str,
    concept: str,
    observation: SecFactObservation,
) -> str:
    return "|".join(
        [
            company.company_name,
            company.cik or "",
            taxonomy,
            concept,
            observation.unit,
            observation.accession_number,
            str(observation.fiscal_year or ""),
            observation.fiscal_period or "",
            observation.start_date or "",
            observation.end_date or "",
        ]
    )


def _build_metric_period(observation: SecFactObservation) -> str:
    if observation.fiscal_year is not None and observation.fiscal_period:
        return f"{observation.fiscal_year}-{observation.fiscal_period}"
    if observation.end_date:
        return observation.end_date
    if observation.filed_date:
        return observation.filed_date
    return observation.accession_number


def _select_observations(observations: Iterable[SecFactObservation]) -> list[SecFactObservation]:
    ordered = list(observations)
    ordered.sort(
        key=lambda observation: (
            observation.filed_date,
            observation.end_date or "",
            observation.start_date or "",
            observation.accession_number,
        ),
        reverse=True,
    )
    return ordered
