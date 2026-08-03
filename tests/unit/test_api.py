"""Unit tests for the public HTTP adapter."""

from __future__ import annotations

import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from app.api import create_app
from app.graph.state import ResearchWorkflowError
from app.clients.sec_client import SecTransportError
from app.models.company import ResolvedCompany
from app.services.evidence_assembly_service import EvidenceBundle, RAGEvidenceRecord
from app.services.workflow_integration_service import run_completed_workflow
from app.services.workflow_output_service import WorkflowOutput, WorkflowOutputInputError, build_workflow_output
from app.services.rag_query_service import RAGQueryError
from app.settings import Settings


class RecordingWorkflow:
    def __init__(self, result: object | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def invoke(self, state: dict[str, object]) -> object:
        self.calls.append(dict(state))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("workflow result was not configured.")
        return self.result


class RecordingClosableClient:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class ApiTests(unittest.TestCase):
    def _build_settings(self, *, api_key: str = "secret") -> Settings:
        return Settings(
            agent_api_key=api_key,
            openai_api_key="demo",
            openai_base_url="https://api.openai.com/v1",
            openai_embedding_model="text-embedding-3-small",
            pinecone_api_key="demo",
            pinecone_index_name="index",
            pinecone_index_host="https://example.com",
            pinecone_namespace_prefix="company",
            pinecone_vector_dimension="3",
            pinecone_api_version=None,
            pinecone_max_upsert_batch_size="10",
            pinecone_max_query_top_k="5",
            tavily_api_key=None,
            news_api_key=None,
            alpha_vantage_api_key=None,
            sec_user_agent="Example App (dev@example.com)",
        )

    def _build_workflow_output(self) -> WorkflowOutput:
        company = ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193")
        evidence = RAGEvidenceRecord(
            result_id="result-1",
            query="Analyze the company's recent financial performance and strategic risks",
            company_name="Apple Inc.",
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-1",
            text="Relevant retrieved passage.",
            similarity_score=0.92,
            retrieval_scope="company:cik:0000320193",
            source_url="https://example.com/doc",
        )
        bundle = EvidenceBundle(
            query="Analyze the company's recent financial performance and strategic risks",
            evidence_count=1,
            evidence=(evidence,),
            source_count=1,
            document_count=1,
        )
        return WorkflowOutput(
            research_query="Analyze the company's recent financial performance and strategic risks",
            resolved_company=company,
            evidence_bundle=bundle,
        )

    def _build_success_dependencies(self, *, workflow: RecordingWorkflow, cleanup_clients: tuple[RecordingClosableClient, ...] = ()) -> SimpleNamespace:
        def cleanup() -> None:
            for client in cleanup_clients:
                client.close()

        return SimpleNamespace(
            workflow=workflow,
            build_workflow_output=build_workflow_output,
            run_completed_workflow=run_completed_workflow,
            cleanup=cleanup,
        )

    def _build_failed_retrieval_state(self) -> dict[str, object]:
        return {
            "research_query": "Analyze the company's recent financial performance and strategic risks",
            "company_input": "Apple Inc.",
            "workflow_status": "failed",
            "current_stage": "failed",
            "errors": (
                ResearchWorkflowError(
                    code="RAGQueryResponseConsistencyError",
                    message="Research retrieval failed.",
                    details=(
                        ("stage", "retrieving_research"),
                        ("error_type", "RAGQueryResponseConsistencyError"),
                    ),
                ),
            ),
        }

    def test_health_returns_ok_and_does_not_construct_provider_clients(self) -> None:
        factory_called = {"count": 0}

        def failing_factory(*args, **kwargs):  # noqa: ANN002, ANN003
            factory_called["count"] += 1
            raise AssertionError("health must not construct provider clients.")

        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=failing_factory,
        )

        with TestClient(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "autonomous-company-research-agent"})
        self.assertEqual(factory_called["count"], 0)

    def test_deployment_info_falls_back_safely_when_railway_variables_are_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            app = create_app(settings_loader=lambda: self._build_settings())

            with TestClient(app) as client:
                response = client.get("/deployment-info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "autonomous-company-research-agent",
                "deployment": {
                    "service_name": "local",
                    "environment": "local",
                    "commit": "unknown",
                },
            },
        )

    def test_deployment_info_truncates_commit_sha_and_hides_full_value(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RAILWAY_SERVICE_NAME": "production-service",
                "RAILWAY_ENVIRONMENT_NAME": "production",
                "RAILWAY_GIT_COMMIT_SHA": "1234567890abcdef1234567890abcdef12345678",
            },
            clear=True,
        ):
            app = create_app(settings_loader=lambda: self._build_settings())

            with TestClient(app) as client:
                response = client.get("/deployment-info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "autonomous-company-research-agent",
                "deployment": {
                    "service_name": "production-service",
                    "environment": "production",
                    "commit": "12345678",
                },
            },
        )
        self.assertNotIn("1234567890abcdef1234567890abcdef12345678", response.text)

    def test_missing_api_key_is_rejected(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "UNAUTHORIZED",
                "message": "Invalid API credentials.",
            },
        )

    def test_invalid_api_key_is_rejected(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "wrong"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "UNAUTHORIZED",
                "message": "Invalid API credentials.",
            },
        )

    def test_research_request_logs_received_marker_without_secrets_or_body(self) -> None:
        workflow_output = self._build_workflow_output()
        completed_workflow = RecordingWorkflow(
            result={
                "research_query": workflow_output.research_query,
                "resolved_company": workflow_output.resolved_company,
                "evidence_bundle": workflow_output.evidence_bundle,
                "workflow_status": "completed",
                "current_stage": "completed",
                "errors": (),
            }
        )
        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=completed_workflow,
                build_workflow_output=build_workflow_output,
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: None,
            ),
        )

        with TestClient(app) as client, self.assertLogs("app.api", level="INFO") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(
                record.getMessage().startswith(
                    "research_request_received route=/research service_name="
                )
                for record in logs.records
            )
        )
        joined_logs = "\n".join(record.getMessage() for record in logs.records)
        for forbidden in (
            "secret",
            "Apple Inc.",
            "AAPL",
            "0000320193",
            "Analyze the company's recent financial performance and strategic risks",
            "Authorization",
            "Bearer",
            "vector",
            "evidence",
            "provider",
        ):
            self.assertNotIn(forbidden, joined_logs)

    def test_invalid_company_input_returns_400(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "  ",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INVALID_RESEARCH_REQUEST",
                "message": "Company, ticker, CIK and research query are required.",
            },
        )

    def test_invalid_ticker_input_returns_400(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INVALID_RESEARCH_REQUEST",
                "message": "Company, ticker, CIK and research query are required.",
            },
        )

    def test_invalid_cik_input_returns_400(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "abc",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INVALID_RESEARCH_REQUEST",
                "message": "Company, ticker, CIK and research query are required.",
            },
        )

    def test_invalid_query_input_returns_400(self) -> None:
        app = create_app(settings_loader=lambda: self._build_settings())

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": " ",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INVALID_RESEARCH_REQUEST",
                "message": "Company, ticker, CIK and research query are required.",
            },
        )

    def test_valid_request_builds_canonical_override_arguments(self) -> None:
        captured: dict[str, object] = {}

        def factory(settings, **kwargs):  # noqa: ANN001, ANN003
            captured["settings"] = settings
            captured["kwargs"] = dict(kwargs)
            workflow = RecordingWorkflow(
                result={
                    "research_query": "Analyze the company's recent financial performance and strategic risks",
                    "resolved_company": ResolvedCompany(company_name="Apple Inc.", ticker="AAPL", cik="0000320193"),
                    "evidence_bundle": self._build_workflow_output().evidence_bundle,
                    "workflow_status": "completed",
                    "current_stage": "completed",
                    "errors": (),
                }
            )
            return self._build_success_dependencies(workflow=workflow)

        app = create_app(settings_loader=lambda: self._build_settings(), dependencies_factory=factory)

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": " Apple Inc. ",
                    "ticker": "aapl",
                    "cik": "320193",
                    "query": " Analyze the company's recent financial performance and strategic risks ",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["kwargs"], {"company": "Apple Inc.", "resolved_ticker": "AAPL", "resolved_cik": "0000320193"})
        self.assertIsInstance(captured["settings"], Settings)

    def test_valid_successful_workflow_returns_existing_success_contract(self) -> None:
        workflow_output = self._build_workflow_output()
        workflow = RecordingWorkflow(
            result={
                "research_query": workflow_output.research_query,
                "resolved_company": workflow_output.resolved_company,
                "evidence_bundle": workflow_output.evidence_bundle,
                "workflow_status": "completed",
                "current_stage": "completed",
                "errors": (),
            }
        )
        dependencies = self._build_success_dependencies(workflow=workflow)

        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: dependencies,  # noqa: ARG005
        )

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), run_completed_workflow(workflow_output))
        self.assertEqual(
            workflow.calls,
            [
                {
                    "research_query": "Analyze the company's recent financial performance and strategic risks",
                    "company_input": "Apple Inc.",
                }
            ],
        )

    def test_provider_failure_returns_safe_502_and_hides_details(self) -> None:
        workflow = RecordingWorkflow(error=SecTransportError("secret provider detail"))
        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=workflow,
                build_workflow_output=build_workflow_output,
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: None,
            ),
        )

        with TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "RESEARCH_RETRIEVAL_FAILED",
                "message": "Research retrieval failed.",
            },
        )
        self.assertNotIn("secret provider detail", response.text)
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=workflow_execution error_type=SecTransportError cause_type=None response_status=502",
        )

    def test_unexpected_failure_returns_safe_500_and_hides_details(self) -> None:
        def factory(settings, **kwargs):  # noqa: ANN001, ANN003
            raise RuntimeError("unexpected secret detail")

        app = create_app(settings_loader=lambda: self._build_settings(), dependencies_factory=factory)

        with TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INTERNAL_RESEARCH_ERROR",
                "message": "The research workflow could not be completed.",
            },
        )
        self.assertNotIn("unexpected secret detail", response.text)
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=unexpected error_type=RuntimeError cause_type=None response_status=500",
        )

    def test_failed_workflow_state_with_retrieval_error_returns_502_and_logs_safe_metadata(self) -> None:
        cleanup_client = RecordingClosableClient()
        workflow = RecordingWorkflow(result=self._build_failed_retrieval_state())
        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=workflow,
                build_workflow_output=lambda state: self.fail("build_workflow_output must not run for retrieval failures."),
                run_completed_workflow=run_completed_workflow,
                cleanup=cleanup_client.close,
            ),
        )

        with TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "RESEARCH_RETRIEVAL_FAILED",
                "message": "Research retrieval failed.",
            },
        )
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=workflow_execution error_type=RAGQueryResponseConsistencyError cause_type=None response_status=502",
        )
        self.assertNotIn("Analyze the company's recent financial performance and strategic risks", logs.records[0].getMessage())
        self.assertNotIn("secret", logs.records[0].getMessage())
        self.assertEqual(cleanup_client.close_count, 1)

    def test_output_failure_with_retrieval_cause_returns_502_and_hides_details(self) -> None:
        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=RecordingWorkflow(result={"workflow_status": "completed", "current_stage": "completed"}),
                build_workflow_output=build_workflow_output,
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: None,
            ),
        )

        def failing_build_workflow_output(state):  # noqa: ANN001
            del state
            raise WorkflowOutputInputError("output secret") from RAGQueryError("nested secret")

        with patch("app.api.build_workflow_output", side_effect=failing_build_workflow_output), TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "RESEARCH_RETRIEVAL_FAILED",
                "message": "Research retrieval failed.",
            },
        )
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=workflow_output error_type=WorkflowOutputInputError cause_type=RAGQueryError response_status=502",
        )
        self.assertNotIn("output secret", logs.records[0].getMessage())
        self.assertNotIn("nested secret", logs.records[0].getMessage())

    def test_genuine_output_input_error_without_retrieval_cause_remains_500(self) -> None:
        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: SimpleNamespace(  # noqa: ARG005
                workflow=RecordingWorkflow(result={"workflow_status": "completed", "current_stage": "completed"}),
                build_workflow_output=build_workflow_output,
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: None,
            ),
        )

        def failing_build_workflow_output(state):  # noqa: ANN001
            del state
            raise WorkflowOutputInputError("output secret")

        with patch("app.api.build_workflow_output", side_effect=failing_build_workflow_output), TestClient(app) as client, self.assertLogs("app.api", level="WARNING") as logs:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "status": "failed",
                "error_code": "INTERNAL_RESEARCH_ERROR",
                "message": "The research workflow could not be completed.",
            },
        )
        self.assertEqual(
            logs.records[0].getMessage(),
            "research_request_failed stage=workflow_output error_type=WorkflowOutputInputError cause_type=None response_status=500",
        )
        self.assertNotIn("output secret", logs.records[0].getMessage())

    def test_clients_close_exactly_once_on_success(self) -> None:
        workflow_output = self._build_workflow_output()
        workflow = RecordingWorkflow(
            result={
                "research_query": workflow_output.research_query,
                "resolved_company": workflow_output.resolved_company,
                "evidence_bundle": workflow_output.evidence_bundle,
                "workflow_status": "completed",
                "current_stage": "completed",
                "errors": (),
            }
        )
        first_client = RecordingClosableClient()
        second_client = RecordingClosableClient()
        dependencies = self._build_success_dependencies(workflow=workflow, cleanup_clients=(first_client, second_client))

        app = create_app(
            settings_loader=lambda: self._build_settings(),
            dependencies_factory=lambda settings, **kwargs: dependencies,  # noqa: ARG005
        )

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(first_client.close_count, 1)
        self.assertEqual(second_client.close_count, 1)

    def test_create_app_does_not_duplicate_logging_handlers(self) -> None:
        root_logger = logging.getLogger()
        before = list(root_logger.handlers)

        create_app(settings_loader=lambda: self._build_settings())
        after_first = list(root_logger.handlers)
        create_app(settings_loader=lambda: self._build_settings())
        after_second = list(root_logger.handlers)

        self.assertEqual(len(after_first), len(after_second))
        self.assertGreaterEqual(len(after_first), len(before))

    def test_clients_close_exactly_once_on_failure(self) -> None:
        first_client = RecordingClosableClient()
        second_client = RecordingClosableClient()
        workflow = RecordingWorkflow(error=RuntimeError("boom"))

        def factory(settings, **kwargs):  # noqa: ANN001, ANN003
            return SimpleNamespace(
                workflow=workflow,
                build_workflow_output=build_workflow_output,
                run_completed_workflow=run_completed_workflow,
                cleanup=lambda: (first_client.close(), second_client.close()),
            )

        app = create_app(settings_loader=lambda: self._build_settings(), dependencies_factory=factory)

        with TestClient(app) as client:
            response = client.post(
                "/research",
                headers={"X-API-Key": "secret"},
                json={
                    "company": "Apple Inc.",
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "query": "Analyze the company's recent financial performance and strategic risks",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(first_client.close_count, 1)
        self.assertEqual(second_client.close_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
