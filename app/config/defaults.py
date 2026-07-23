"""Runtime defaults for the foundation stage."""

from __future__ import annotations

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


def build_runtime_config(settings: Settings) -> RuntimeConfig:
    """Map settings into the canonical runtime configuration."""

    return RuntimeConfig(
        openai_api_key=settings.openai_api_key,
        pinecone_api_key=settings.pinecone_api_key,
        pinecone_index_name=settings.pinecone_index_name,
        tavily_api_key=settings.tavily_api_key,
        news_api_key=settings.news_api_key,
        alpha_vantage_api_key=settings.alpha_vantage_api_key,
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
