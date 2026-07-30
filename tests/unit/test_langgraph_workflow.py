"""Unit tests for the LangGraph workflow foundation."""

from __future__ import annotations

import unittest

from app.models.company import ResolvedCompany
from app.models.execution import RuntimeConfig
from app.models.request import ResearchRequest
from app.services.company_resolution_service import CompanyResolutionNoMatchError


class FakeSecClient:
    """In-memory SEC client placeholder for offline workflow tests."""

    pass


class RecordingCompanyResolver:
    """Resolver fake that records every call."""

    def __init__(self, result: ResolvedCompany | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[ResearchRequest, RuntimeConfig, FakeSecClient]] = []

    def __call__(
        self,
        request: ResearchRequest,
        runtime_config: RuntimeConfig,
        sec_client: FakeSecClient,
    ) -> ResolvedCompany:
        self.calls.append((request, runtime_config, sec_client))
        if self.error is not None:
            raise self.error
        if self.result is None:
            return ResolvedCompany(company_name=request.company_name or "Example Corp", ticker="EXM", cik="0000000001")
        return self.result


class LangGraphWorkflowTests(unittest.TestCase):
    """Focused tests for the workflow foundation."""

    def setUp(self) -> None:
        self.runtime_config = RuntimeConfig(sec_user_agent="Example App (dev@example.com)")
        self.sec_client = FakeSecClient()
        self.resolved_company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")

    def tearDown(self) -> None:
        for module_name in tuple(__import__("sys").modules):
            if module_name.startswith("langgraph") or module_name.startswith("langchain_core"):
                __import__("sys").modules.pop(module_name, None)

    def _build_workflow(self, resolver: RecordingCompanyResolver):
        from app.graph.workflow import build_research_workflow

        return build_research_workflow(
            company_resolution_dependency=resolver,
            runtime_config=self.runtime_config,
            sec_client=self.sec_client,
        )

    def test_graph_builds_compiles_and_registers_expected_nodes(self) -> None:
        workflow = self._build_workflow(RecordingCompanyResolver(self.resolved_company))

        graph = workflow.get_graph()
        self.assertEqual(
            set(graph.nodes),
            {
                "__start__",
                "initialize_research",
                "resolve_company",
                "validate_company",
                "complete_workflow",
                "fail_workflow",
                "__end__",
            },
        )

        edge_pairs = {(edge.source, edge.target, edge.conditional) for edge in graph.edges}
        self.assertIn(("__start__", "initialize_research", False), edge_pairs)
        self.assertIn(("initialize_research", "resolve_company", True), edge_pairs)
        self.assertIn(("initialize_research", "fail_workflow", True), edge_pairs)
        self.assertIn(("resolve_company", "validate_company", True), edge_pairs)
        self.assertIn(("resolve_company", "fail_workflow", True), edge_pairs)
        self.assertIn(("validate_company", "complete_workflow", True), edge_pairs)
        self.assertIn(("validate_company", "fail_workflow", True), edge_pairs)
        self.assertIn(("complete_workflow", "__end__", False), edge_pairs)
        self.assertIn(("fail_workflow", "__end__", False), edge_pairs)

        for forbidden_node in ("provider_collection", "rag", "evidence", "report", "react_agent"):
            self.assertNotIn(forbidden_node, graph.nodes)

    def test_graph_does_not_compile_during_import(self) -> None:
        import app.graph.workflow as workflow_module

        compiled_graphs = [
            value
            for value in vars(workflow_module).values()
            if value.__class__.__name__ == "CompiledStateGraph"
        ]
        self.assertEqual(compiled_graphs, [])

    def test_successful_execution_preserves_input_and_resolves_company_once(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver)
        initial_state = {
            "research_query": "  Assess Apple Inc.  ",
            "company_input": "  Apple Inc.  ",
        }
        original_state = dict(initial_state)

        result = workflow.invoke(initial_state)

        self.assertEqual(initial_state, original_state)
        self.assertEqual(len(resolver.calls), 1)
        request, runtime_config, sec_client = resolver.calls[0]
        self.assertEqual(request.company_name, "  Apple Inc.  ")
        self.assertIs(runtime_config, self.runtime_config)
        self.assertIs(sec_client, self.sec_client)
        self.assertEqual(result["research_query"], "  Assess Apple Inc.  ")
        self.assertEqual(result["company_input"], "  Apple Inc.  ")
        self.assertEqual(result["resolved_company"], self.resolved_company)
        self.assertEqual(result["workflow_status"], "completed")
        self.assertEqual(result["current_stage"], "completed")
        self.assertEqual(result["errors"], ())

    def test_invalid_initial_query_routes_to_failure_without_resolution(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver)

        result = workflow.invoke({"research_query": "", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 0)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_research_query")

    def test_invalid_company_input_routes_to_failure_without_resolution(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": 123})

        self.assertEqual(len(resolver.calls), 0)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_company_input")

    def test_resolution_failure_routes_to_failure_and_preserves_typed_error(self) -> None:
        resolver = RecordingCompanyResolver(error=CompanyResolutionNoMatchError("No SEC company matched the supplied ticker."))
        workflow = self._build_workflow(resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "CompanyResolutionNoMatchError")
        self.assertNotIn("resolved_company", result)

    def test_invalid_resolution_output_fails_safely(self) -> None:
        resolver = RecordingCompanyResolver(result="not a company")  # type: ignore[arg-type]
        workflow = self._build_workflow(resolver)

        result = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(result["workflow_status"], "failed")
        self.assertEqual(result["current_stage"], "failed")
        self.assertEqual(result["errors"][0].code, "invalid_resolved_company")
        self.assertNotIn("resolved_company", result)

    def test_repeated_invocations_are_deterministic(self) -> None:
        resolver = RecordingCompanyResolver(self.resolved_company)
        workflow = self._build_workflow(resolver)

        first = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})
        second = workflow.invoke({"research_query": "Assess Apple", "company_input": "Apple Inc."})

        self.assertEqual(first, second)
        self.assertEqual(len(resolver.calls), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
