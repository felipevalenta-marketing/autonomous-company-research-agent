"""Environment settings for the project foundation."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.config.constants import (
    ALPHA_VANTAGE_API_KEY_ENV,
    AGENT_API_KEY_ENV,
    OPENAI_BASE_URL_ENV,
    OPENAI_EMBEDDING_MODEL_ENV,
    NEWS_API_KEY_ENV,
    OPENAI_API_KEY_ENV,
    PINECONE_API_KEY_ENV,
    PINECONE_API_VERSION_ENV,
    PINECONE_INDEX_HOST_ENV,
    PINECONE_INDEX_NAME_ENV,
    PINECONE_MAX_QUERY_TOP_K_ENV,
    PINECONE_MAX_UPSERT_BATCH_SIZE_ENV,
    PINECONE_NAMESPACE_PREFIX_ENV,
    PINECONE_VECTOR_DIMENSION_ENV,
    SEC_USER_AGENT_ENV,
    TAVILY_API_KEY_ENV,
)


@dataclass(frozen=True)
class Settings:
    """Immutable environment settings."""

    agent_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_embedding_model: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index_name: str | None = None
    pinecone_index_host: str | None = None
    pinecone_namespace_prefix: str | None = None
    pinecone_vector_dimension: str | None = None
    pinecone_api_version: str | None = None
    pinecone_max_upsert_batch_size: str | None = None
    pinecone_max_query_top_k: str | None = None
    tavily_api_key: str | None = None
    news_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    sec_user_agent: str | None = None


def load_settings() -> Settings:
    """Load settings from environment variables and the local `.env` file."""
    load_dotenv()
    return Settings(
        agent_api_key=os.getenv(AGENT_API_KEY_ENV),
        openai_api_key=os.getenv(OPENAI_API_KEY_ENV),
        openai_base_url=os.getenv(OPENAI_BASE_URL_ENV),
        openai_embedding_model=os.getenv(OPENAI_EMBEDDING_MODEL_ENV),
        pinecone_api_key=os.getenv(PINECONE_API_KEY_ENV),
        pinecone_index_name=os.getenv(PINECONE_INDEX_NAME_ENV),
        pinecone_index_host=os.getenv(PINECONE_INDEX_HOST_ENV),
        pinecone_namespace_prefix=os.getenv(PINECONE_NAMESPACE_PREFIX_ENV),
        pinecone_vector_dimension=os.getenv(PINECONE_VECTOR_DIMENSION_ENV),
        pinecone_api_version=os.getenv(PINECONE_API_VERSION_ENV),
        pinecone_max_upsert_batch_size=os.getenv(PINECONE_MAX_UPSERT_BATCH_SIZE_ENV),
        pinecone_max_query_top_k=os.getenv(PINECONE_MAX_QUERY_TOP_K_ENV),
        tavily_api_key=os.getenv(TAVILY_API_KEY_ENV),
        news_api_key=os.getenv(NEWS_API_KEY_ENV),
        alpha_vantage_api_key=os.getenv(ALPHA_VANTAGE_API_KEY_ENV),
        sec_user_agent=os.getenv(SEC_USER_AGENT_ENV),
    )
