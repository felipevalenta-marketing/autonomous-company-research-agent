"""Application-service orchestration for SEC collection."""

from __future__ import annotations

from typing import Protocol

from app.clients.sec_dtos import SecCompanyFactsResponse, SecSubmissionsResponse
from app.models.company import ResolvedCompany
from app.models.documents import DocumentRecord
from app.models.execution import RuntimeConfig
from app.models.providers import FinancialMetric
from app.models.sources import SourceRecord
from app.services.sec_normalization_service import normalize_sec_company_facts, normalize_sec_submissions
from app.services.source_registration_service import register_sources


class SecCollectionError(Exception):
    """Base exception for SEC collection orchestration failures."""


class SecCollectionInputError(SecCollectionError):
    """Raised when the SEC collection service receives invalid input."""


class SecCollectionClient(Protocol):
    """Narrow SEC client contract required by the collection service."""

    def get_company_submissions(self, cik: int | str) -> SecSubmissionsResponse:
        """Return validated SEC submissions for a company."""

    def get_company_facts(self, cik: int | str) -> SecCompanyFactsResponse:
        """Return validated SEC company facts for a company."""


def collect_sec_documents(
    resolved_company: ResolvedCompany,
    sec_client: SecCollectionClient,
    runtime_config: RuntimeConfig | None = None,
) -> tuple[tuple[DocumentRecord, ...], tuple[SourceRecord, ...]]:
    """Collect deterministic SEC filing documents and source records."""

    cik = _require_company_cik(resolved_company)
    submissions = sec_client.get_company_submissions(cik)
    documents, sources = normalize_sec_submissions(resolved_company, submissions, runtime_config=runtime_config)
    return tuple(documents), register_sources(sources)


def collect_financial_data(
    resolved_company: ResolvedCompany,
    sec_client: SecCollectionClient,
    runtime_config: RuntimeConfig | None = None,
) -> tuple[FinancialMetric, ...]:
    """Collect deterministic SEC company-facts metrics."""

    cik = _require_company_cik(resolved_company)
    company_facts = sec_client.get_company_facts(cik)
    metrics = normalize_sec_company_facts(resolved_company, company_facts, runtime_config=runtime_config)
    return tuple(metrics)


def _require_company_cik(resolved_company: ResolvedCompany) -> str:
    cik = resolved_company.cik
    if cik is None or not cik.strip():
        raise SecCollectionInputError("Resolved company must include a SEC CIK.")
    return cik.strip()
