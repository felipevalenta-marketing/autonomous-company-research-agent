"""Smoke tests for the project foundation."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app.main import main
from app.settings import Settings, load_settings
from app.state import ResearchState


class SmokeTest(unittest.TestCase):
    """Minimal checks for the initial project structure."""

    def test_main_is_callable(self) -> None:
        self.assertTrue(callable(main))

    def test_research_state_imports(self) -> None:
        self.assertEqual(ResearchState.__name__, "ResearchState")

    def test_load_settings_returns_settings(self) -> None:
        settings = load_settings()
        self.assertIsInstance(settings, Settings)

    def test_missing_env_vars_do_not_fail(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsInstance(settings, Settings)

    def test_settings_fields_are_optional_strings(self) -> None:
        settings = load_settings()
        for value in settings.__dict__.values():
            self.assertTrue(value is None or isinstance(value, str))

    def test_data_directories_exist(self) -> None:
        self.assertTrue(Path("data/raw").is_dir())
        self.assertTrue(Path("data/processed").is_dir())


if __name__ == "__main__":
    unittest.main()
