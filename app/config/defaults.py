"""Runtime defaults for the foundation stage."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.constants import (
    OPENAI_DEFAULT_EMBEDDING_MODEL,
    OPENAI_MAX_EMBEDDING_BATCH_SIZE,
    PINECONE_DEFAULT_MAX_QUERY_TOP_K,
    PINECONE_DEFAULT_MAX_UPSERT_BATCH_SIZE,
    PINECONE_DEFAULT_NAMESPACE_PREFIX,
    PINECONE_DEFAULT_VECTOR_DIMENSION,
)
from app.models.execution import RuntimeConfig
from app.settings import Settings

DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_OUTPUT_DIRECTORY = "outputs"
DEFAULT_RAW_DATA_DIRECTORY = "data/raw"
DEFAULT_PROCESSED_DATA_DIRECTORY = "data/processed"

DEFAULT_ENABLE_PDF_EXPORT = True
DEFAULT_ENABLE_NEWS = False
DEFAULT_ENABLE_MARKET_RESEARCH = False
DEFAULT_ENABLE_OFFICIAL_COMPANY_SOURCES = False

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_EMBEDDING_MODEL = OPENAI_DEFAULT_EMBEDDING_MODEL
DEFAULT_OPENAI_EMBEDDING_BATCH_SIZE = OPENAI_MAX_EMBEDDING_BATCH_SIZE

DEFAULT_NEWS_LANGUAGE = "en"
DEFAULT_NEWS_SORT_BY = "publishedAt"
DEFAULT_NEWS_PAGE_SIZE = 20
DEFAULT_NEWS_MAX_PAGE_SIZE = 100
DEFAULT_NEWS_LOOKBACK_DAYS = 7

DEFAULT_TAVILY_TOPIC = "general"
DEFAULT_TAVILY_MAX_RESULTS = 5
DEFAULT_TAVILY_LOOKBACK_DAYS = 30
DEFAULT_TAVILY_MAX_LOOKBACK_DAYS = 365


@dataclass(frozen=True, slots=True)
class PineconeConfig:
    """Derived Pinecone configuration."""

    api_key: str | None
    index_host: str | None
    namespace_prefix: str
    vector_dimension: int
    api_version: str | None
    max_upsert_batch_size: int
    max_query_top_k: int

    def __post_init__(self) -> None:
        if not self.namespace_prefix.strip():
            raise ValueError("namespace_prefix must not be empty.")
        if self.vector_dimension <= 0:
            raise ValueError("vector_dimension must be positive.")
        if self.max_upsert_batch_size <= 0:
            raise ValueError("max_upsert_batch_size must be positive.")
        if self.max_query_top_k <= 0:
            raise ValueError("max_query_top_k must be positive.")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _positive_int(value: str | None, default: int, field_name: str) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return parsed


def build_runtime_config(settings: Settings) -> RuntimeConfig:
    """Map settings into the canonical runtime configuration."""

    return RuntimeConfig(
        openai_api_key=settings.openai_api_key,
        pinecone_api_key=settings.pinecone_api_key,
        pinecone_index_name=settings.pinecone_index_name,
        tavily_api_key=settings.tavily_api_key,
        news_api_key=settings.news_api_key,
        alpha_vantage_api_key=settings.alpha_vantage_api_key,
        sec_user_agent=settings.sec_user_agent,
        max_retries=DEFAULT_MAX_RETRIES,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        output_directory=DEFAULT_OUTPUT_DIRECTORY,
        raw_data_directory=DEFAULT_RAW_DATA_DIRECTORY,
        processed_data_directory=DEFAULT_PROCESSED_DATA_DIRECTORY,
        enable_pdf_export=DEFAULT_ENABLE_PDF_EXPORT,
        enable_news=DEFAULT_ENABLE_NEWS,
        enable_market_research=DEFAULT_ENABLE_MARKET_RESEARCH,
        enable_official_company_sources=DEFAULT_ENABLE_OFFICIAL_COMPANY_SOURCES,
    )


def build_pinecone_config(settings: Settings) -> PineconeConfig:
    """Map settings into the Pinecone-specific runtime configuration."""

    return PineconeConfig(
        api_key=settings.pinecone_api_key,
        index_host=_optional_text(settings.pinecone_index_host),
        namespace_prefix=_optional_text(settings.pinecone_namespace_prefix) or PINECONE_DEFAULT_NAMESPACE_PREFIX,
        vector_dimension=_positive_int(
            settings.pinecone_vector_dimension,
            PINECONE_DEFAULT_VECTOR_DIMENSION,
            "pinecone_vector_dimension",
        ),
        api_version=_optional_text(settings.pinecone_api_version),
        max_upsert_batch_size=_positive_int(
            settings.pinecone_max_upsert_batch_size,
            PINECONE_DEFAULT_MAX_UPSERT_BATCH_SIZE,
            "pinecone_max_upsert_batch_size",
        ),
        max_query_top_k=_positive_int(
            settings.pinecone_max_query_top_k,
            PINECONE_DEFAULT_MAX_QUERY_TOP_K,
            "pinecone_max_query_top_k",
        ),
    )
