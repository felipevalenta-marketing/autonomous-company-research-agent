"""Environment settings for the project foundation."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.config.constants import (
    ALPHA_VANTAGE_API_KEY_ENV,
    NEWS_API_KEY_ENV,
    OPENAI_API_KEY_ENV,
    PINECONE_API_KEY_ENV,
    PINECONE_INDEX_NAME_ENV,
    TAVILY_API_KEY_ENV,
)


@dataclass(frozen=True)
class Settings:
    """Immutable environment settings."""

    openai_api_key: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index_name: str | None = None
    tavily_api_key: str | None = None
    news_api_key: str | None = None
    alpha_vantage_api_key: str | None = None


def load_settings() -> Settings:
    """Load settings from environment variables and the local `.env` file."""
    load_dotenv()
    return Settings(
        openai_api_key=os.getenv(OPENAI_API_KEY_ENV),
        pinecone_api_key=os.getenv(PINECONE_API_KEY_ENV),
        pinecone_index_name=os.getenv(PINECONE_INDEX_NAME_ENV),
        tavily_api_key=os.getenv(TAVILY_API_KEY_ENV),
        news_api_key=os.getenv(NEWS_API_KEY_ENV),
        alpha_vantage_api_key=os.getenv(ALPHA_VANTAGE_API_KEY_ENV),
    )
