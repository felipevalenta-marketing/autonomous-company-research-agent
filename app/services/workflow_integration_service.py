"""Minimal integration boundary for external workflow automation."""

from __future__ import annotations

from collections.abc import Callable

from app.services.workflow_output_service import WorkflowOutput
from app.services.workflow_serialization_service import (
    WorkflowSerializationConsistencyError,
    WorkflowSerializationError,
    WorkflowSerializationInputError,
    serialize_workflow_output,
)


class WorkflowIntegrationError(Exception):
    """Base exception for workflow integration failures."""


class WorkflowIntegrationInputError(WorkflowIntegrationError):
    """Raised when workflow integration inputs are invalid."""


class WorkflowIntegrationConsistencyError(WorkflowIntegrationError):
    """Raised when the serialization dependency returns an invalid result."""


def run_completed_workflow(
    workflow_output: WorkflowOutput,
    *,
    serialization_dependency: Callable[[WorkflowOutput], dict[str, object]] = serialize_workflow_output,
) -> dict[str, object]:
    """Serialize completed workflow output for external automation consumers."""

    normalized_workflow_output = _require_workflow_output(workflow_output)
    _require_serialization_dependency(serialization_dependency)

    try:
        payload = serialization_dependency(normalized_workflow_output)
    except (WorkflowSerializationInputError, WorkflowSerializationConsistencyError):
        raise
    except WorkflowSerializationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise WorkflowIntegrationError("workflow integration failed.") from exc

    if not isinstance(payload, dict):
        raise WorkflowIntegrationConsistencyError("serialization dependency must return a dict.")
    return payload


def _require_workflow_output(value: object) -> WorkflowOutput:
    if not isinstance(value, WorkflowOutput):
        raise WorkflowIntegrationInputError("workflow_output must be a WorkflowOutput instance.")
    return value


def _require_serialization_dependency(value: object) -> Callable[[WorkflowOutput], dict[str, object]]:
    if not callable(value):
        raise WorkflowIntegrationInputError("serialization_dependency must be callable.")
    return value
