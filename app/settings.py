"""Environment settings for the project foundation."""

from dataclasses import dataclass
import os


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
    """Load settings from environment variables."""
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        pinecone_api_key=os.getenv("PINECONE_API_KEY"),
        pinecone_index_name=os.getenv("PINECONE_INDEX_NAME"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        news_api_key=os.getenv("NEWS_API_KEY"),
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY"),
    )
