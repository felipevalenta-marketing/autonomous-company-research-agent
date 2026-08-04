"""Source-level checks for the n8n workflow SDK export."""

from __future__ import annotations

import unittest
from pathlib import Path


class N8nWorkflowSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_path = Path("n8n/workflows/autonomous_company_research_agent.workflow.ts")
        self.source = self.source_path.read_text(encoding="utf-8")

    def test_workflow_source_uses_real_railway_endpoint_and_demo_fields(self) -> None:
        self.assertIn(
            "https://autonomous-company-research-agent-production.up.railway.app/research",
            self.source,
        )
        self.assertIn("Autonomous Research Agent API", self.source)
        self.assertIn("Array.isArray(($json.body ?? $json.data ?? $json).evidence_bundle?.evidence)", self.source)
        self.assertIn("name: 'company'", self.source)
        self.assertIn("name: 'key_evidence'", self.source)
        self.assertIn("name: 'markdown'", self.source)
        self.assertIn("status: 'completed'", self.source)
        self.assertNotIn("Public HTTPS /research endpoint for the Python agent", self.source)

    def test_workflow_source_contains_required_presentation_notes(self) -> None:
        for needle in (
            "## Input",
            "## Validation",
            "## Research Agent",
            "## Output",
            "## Presentation",
            "## Architecture",
        ):
            self.assertIn(needle, self.source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
