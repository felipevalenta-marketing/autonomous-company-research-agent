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
)
from app.config.constants import SEC_USER_AGENT_ENV
from app.models.execution import RuntimeConfig
from app.settings import Settings, load_settings


class ConfigurationTests(unittest.TestCase):
    """Tests for settings loading and runtime mapping."""

    def test_load_settings_reads_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "PINECONE_API_KEY": "pinecone-key",
                "PINECONE_INDEX_NAME": "research-index",
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
        self.assertEqual(settings.pinecone_api_key, "pinecone-key")
        self.assertEqual(settings.pinecone_index_name, "research-index")
        self.assertEqual(settings.tavily_api_key, "tavily-key")
        self.assertEqual(settings.news_api_key, "news-key")
        self.assertEqual(settings.alpha_vantage_api_key, "alpha-key")
        self.assertEqual(settings.sec_user_agent, "Example App (dev@example.com)")

    def test_missing_env_vars_do_not_fail(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertIsInstance(settings, Settings)
        self.assertIsNone(settings.sec_user_agent)
        for value in settings.__dict__.values():
            self.assertTrue(value is None or isinstance(value, str))

    def test_runtime_config_mapping_uses_safe_defaults(self) -> None:
        settings = Settings(
            openai_api_key="openai-key",
            pinecone_api_key="pinecone-key",
            pinecone_index_name="research-index",
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
