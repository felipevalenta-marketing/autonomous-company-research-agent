"""Configuration unit tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config.defaults import (
    DEFAULT_ENABLE_MARKET_RESEARCH,
    DEFAULT_ENABLE_NEWS,
    DEFAULT_ENABLE_OFFICIAL_COMPANY_SOURCES,
    DEFAULT_MAX_RETRIES,
    DEFAULT_OUTPUT_DIRECTORY,
    DEFAULT_PROCESSED_DATA_DIRECTORY,
    DEFAULT_RAW_DATA_DIRECTORY,
    DEFAULT_TIMEOUT_SECONDS,
    build_runtime_config,
    build_pinecone_config,
    PineconeConfig,
)
from app.config.constants import (
    PINECONE_API_VERSION_ENV,
    PINECONE_INDEX_HOST_ENV,
    PINECONE_MAX_QUERY_TOP_K_ENV,
    PINECONE_MAX_UPSERT_BATCH_SIZE_ENV,
    PINECONE_NAMESPACE_PREFIX_ENV,
    PINECONE_VECTOR_DIMENSION_ENV,
    SEC_USER_AGENT_ENV,
)
from app.models.execution import RuntimeConfig
from app.settings import Settings, load_settings


class ConfigurationTests(unittest.TestCase):
    """Tests for settings loading and runtime mapping."""

    def test_load_settings_reads_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
                "PINECONE_API_KEY": "pinecone-key",
                "PINECONE_INDEX_NAME": "research-index",
                PINECONE_INDEX_HOST_ENV: "https://example-index.svc.pinecone.io",
                PINECONE_NAMESPACE_PREFIX_ENV: "company",
                PINECONE_VECTOR_DIMENSION_ENV: "1536",
                PINECONE_API_VERSION_ENV: "2024-07",
                PINECONE_MAX_UPSERT_BATCH_SIZE_ENV: "50",
                PINECONE_MAX_QUERY_TOP_K_ENV: "10",
                "TAVILY_API_KEY": "tavily-key",
                "NEWS_API_KEY": "news-key",
                "ALPHA_VANTAGE_API_KEY": "alpha-key",
                SEC_USER_AGENT_ENV: "Example App (dev@example.com)",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertIsInstance(settings, Settings)
        self.assertEqual(settings.openai_api_key, "openai-key")
        self.assertEqual(settings.openai_base_url, "https://api.openai.com/v1")
        self.assertEqual(settings.openai_embedding_model, "text-embedding-3-small")
        self.assertEqual(settings.pinecone_api_key, "pinecone-key")
        self.assertEqual(settings.pinecone_index_name, "research-index")
        self.assertEqual(settings.pinecone_index_host, "https://example-index.svc.pinecone.io")
        self.assertEqual(settings.pinecone_namespace_prefix, "company")
        self.assertEqual(settings.pinecone_vector_dimension, "1536")
        self.assertEqual(settings.pinecone_api_version, "2024-07")
        self.assertEqual(settings.pinecone_max_upsert_batch_size, "50")
        self.assertEqual(settings.pinecone_max_query_top_k, "10")
        self.assertEqual(settings.tavily_api_key, "tavily-key")
        self.assertEqual(settings.news_api_key, "news-key")
        self.assertEqual(settings.alpha_vantage_api_key, "alpha-key")
        self.assertEqual(settings.sec_user_agent, "Example App (dev@example.com)")

    def test_missing_env_vars_do_not_fail(self) -> None:
        with patch("app.settings.load_dotenv", return_value=False), patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            settings = load_settings()

        self.assertIsInstance(settings, Settings)
        self.assertIsNone(settings.sec_user_agent)
        for value in settings.__dict__.values():
            self.assertTrue(value is None or isinstance(value, str))

        pinecone_config = build_pinecone_config(settings)
        self.assertEqual(pinecone_config.index_host, None)
        self.assertGreater(pinecone_config.vector_dimension, 0)
        self.assertGreater(pinecone_config.max_upsert_batch_size, 0)
        self.assertGreater(pinecone_config.max_query_top_k, 0)

    def test_runtime_config_mapping_uses_safe_defaults(self) -> None:
        settings = Settings(
            openai_api_key="openai-key",
            openai_base_url="https://api.openai.com/v1",
            openai_embedding_model="text-embedding-3-small",
            pinecone_api_key="pinecone-key",
            pinecone_index_name="research-index",
            pinecone_index_host="https://example-index.svc.pinecone.io",
            pinecone_namespace_prefix="company",
            pinecone_vector_dimension="1536",
            pinecone_api_version="2024-07",
            pinecone_max_upsert_batch_size="50",
            pinecone_max_query_top_k="10",
            tavily_api_key="tavily-key",
            news_api_key="news-key",
            alpha_vantage_api_key="alpha-key",
            sec_user_agent="Example App (dev@example.com)",
        )

        runtime_config = build_runtime_config(settings)

        self.assertIsInstance(runtime_config, RuntimeConfig)
        self.assertEqual(runtime_config.openai_api_key, "openai-key")
        self.assertEqual(runtime_config.pinecone_api_key, "pinecone-key")
        self.assertEqual(runtime_config.pinecone_index_name, "research-index")
        self.assertEqual(runtime_config.tavily_api_key, "tavily-key")
        self.assertEqual(runtime_config.news_api_key, "news-key")
        self.assertEqual(runtime_config.alpha_vantage_api_key, "alpha-key")
        self.assertEqual(runtime_config.sec_user_agent, "Example App (dev@example.com)")
        self.assertEqual(runtime_config.max_retries, DEFAULT_MAX_RETRIES)
        self.assertEqual(runtime_config.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(runtime_config.output_directory, DEFAULT_OUTPUT_DIRECTORY)
        self.assertEqual(runtime_config.raw_data_directory, DEFAULT_RAW_DATA_DIRECTORY)
        self.assertEqual(runtime_config.processed_data_directory, DEFAULT_PROCESSED_DATA_DIRECTORY)
        self.assertTrue(runtime_config.enable_pdf_export)
        self.assertEqual(runtime_config.enable_news, DEFAULT_ENABLE_NEWS)
        self.assertEqual(runtime_config.enable_market_research, DEFAULT_ENABLE_MARKET_RESEARCH)
        self.assertEqual(
            runtime_config.enable_official_company_sources,
            DEFAULT_ENABLE_OFFICIAL_COMPANY_SOURCES,
        )

        pinecone_config = build_pinecone_config(settings)

        self.assertIsInstance(pinecone_config, PineconeConfig)
        self.assertEqual(pinecone_config.api_key, "pinecone-key")
        self.assertEqual(pinecone_config.index_host, "https://example-index.svc.pinecone.io")
        self.assertEqual(pinecone_config.namespace_prefix, "company")
        self.assertEqual(pinecone_config.vector_dimension, 1536)
        self.assertEqual(pinecone_config.api_version, "2024-07")
        self.assertEqual(pinecone_config.max_upsert_batch_size, 50)
        self.assertEqual(pinecone_config.max_query_top_k, 10)
