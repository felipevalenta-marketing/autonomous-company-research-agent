"""Smoke tests for the project foundation."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
