"""Execution and observability models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

ExecutionStatus = Literal[
    "initialized",
    "running",
    "completed",
    "completed_with_warnings",
    "failed",
]

ReportValidationStatus = Literal[
    "valid",
    "valid_with_warnings",
    "invalid_repairable",
    "invalid_non_repairable",
]

NodeExecutionStatus = Literal["pending", "running", "completed", "failed", "skipped"]

_EXECUTION_STATUSES: set[str] = {
    "initialized",
    "running",
    "completed",
    "completed_with_warnings",
    "failed",
}
_REPORT_VALIDATION_STATUSES: set[str] = {
    "valid",
    "valid_with_warnings",
    "invalid_repairable",
    "invalid_non_repairable",
}
_NODE_EXECUTION_STATUSES: set[str] = {
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
}


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Execution metadata for a single run."""

    execution_id: str
    created_at: str
    updated_at: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.execution_id, "execution_id")
        _require_text(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Derived non-secret runtime configuration."""

    openai_api_key: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index_name: str | None = None
    tavily_api_key: str | None = None
    news_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    sec_user_agent: str | None = None
    max_retries: int = 3
    timeout_seconds: float = 30.0
    output_directory: str = "outputs"
    raw_data_directory: str = "data/raw"
    processed_data_directory: str = "data/processed"
    enable_pdf_export: bool = True
    enable_news: bool = False
    enable_market_research: bool = False
    enable_official_company_sources: bool = False

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be zero or positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        _require_text(self.output_directory, "output_directory")
        _require_text(self.raw_data_directory, "raw_data_directory")
        _require_text(self.processed_data_directory, "processed_data_directory")


@dataclass(frozen=True, slots=True)
class WorkflowWarning:
    """Non-fatal workflow observation."""

    code: str
    message: str
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.code, "code")
        _require_text(self.message, "message")


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Structured workflow error."""

    code: str
    message: str
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.code, "code")
        _require_text(self.message, "message")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Metadata for a generated artifact."""

    artifact_id: str
    artifact_type: str
    path: str
    checksum: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.artifact_type, "artifact_type")
        _require_text(self.path, "path")


@dataclass(frozen=True, slots=True)
class NodeExecutionRecord:
    """Execution record for a workflow node."""

    node_name: str
    status: NodeExecutionStatus
    started_at: str | None = None
    finished_at: str | None = None
    warnings: list[WorkflowWarning] = field(default_factory=list)
    errors: list[WorkflowError] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.node_name, "node_name")
        if self.status not in _NODE_EXECUTION_STATUSES:
            raise ValueError(f"status must be one of: {sorted(_NODE_EXECUTION_STATUSES)}")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Terminal execution summary."""

    execution_id: str
    status: ExecutionStatus
    final_message: str | None = None
    warnings: list[WorkflowWarning] = field(default_factory=list)
    errors: list[WorkflowError] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.execution_id, "execution_id")
        if self.status not in _EXECUTION_STATUSES:
            raise ValueError(f"status must be one of: {sorted(_EXECUTION_STATUSES)}")
