"""Pydantic models for runbook draft generator.

These models align with:
- specs/006-runbook-generation/data-model.md
- specs/006-runbook-generation/contracts/runbook-generator-openapi.yaml
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TriggeredBy(str, Enum):
    """How the generation run was initiated."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


class SuggestionStatus(str, Enum):
    """Suggestion approval workflow status (Issue #3)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RunbookDraftStatus(str, Enum):
    """Runbook draft readiness status."""

    DRAFT = "draft"
    NEEDS_HUMAN_INPUT = "needs_human_input"


class EditSource(str, Enum):
    """Source of the current draft content."""

    GENERATED = "generated"
    HUMAN = "human"


class RunbookRunRequest(BaseModel):
    """Request body for POST /runbooks/run-once."""

    batch_size: Optional[int] = Field(None, alias="batchSize", ge=1, le=200)
    dry_run: Optional[bool] = Field(None, alias="dryRun")
    suggestion_ids: Optional[List[str]] = Field(None, alias="suggestionIds")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class RunbookGenerateRequest(BaseModel):
    """Request body for POST /runbooks/generate/{suggestionId}."""

    dry_run: Optional[bool] = Field(None, alias="dryRun")
    force_overwrite: Optional[bool] = Field(None, alias="forceOverwrite")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class RunbookOutcomeStatus(str, Enum):
    """Per-suggestion outcome status in a batch run."""

    GENERATED = "generated"
    SKIPPED = "skipped"
    ERROR = "error"


class RunbookOutcome(BaseModel):
    suggestion_id: str = Field(..., alias="suggestionId")
    status: RunbookOutcomeStatus
    error_reason: Optional[str] = Field(None, alias="errorReason")

    model_config = {"populate_by_name": True}


class RunbookRunSummary(BaseModel):
    """Batch execution record for observability (FR-008)."""

    run_id: str = Field(..., alias="runId")
    started_at: datetime = Field(..., alias="startedAt")
    finished_at: datetime = Field(..., alias="finishedAt")
    triggered_by: TriggeredBy = Field(..., alias="triggeredBy")
    batch_size: int = Field(..., alias="batchSize")
    picked_up_count: int = Field(..., alias="pickedUpCount")
    generated_count: int = Field(..., alias="generatedCount")
    skipped_count: int = Field(..., alias="skippedCount")
    error_count: int = Field(..., alias="errorCount")
    processing_duration_ms: int = Field(..., alias="processingDurationMs")
    suggestion_outcomes: Optional[List[RunbookOutcome]] = Field(None, alias="suggestionOutcomes")

    model_config = {"populate_by_name": True}

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "triggered_by": self.triggered_by.value,
            "batch_size": self.batch_size,
            "picked_up_count": self.picked_up_count,
            "generated_count": self.generated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "processing_duration_ms": self.processing_duration_ms,
        }
        if self.suggestion_outcomes is not None:
            result["suggestion_outcomes"] = [
                {"suggestion_id": o.suggestion_id, "status": o.status.value, "error_reason": o.error_reason}
                for o in self.suggestion_outcomes
            ]
        return result


class RunbookGenerateResponse(BaseModel):
    suggestion_id: str = Field(..., alias="suggestionId")
    status: str
    runbook: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class RunbookDraftSource(BaseModel):
    """Lineage tracking for runbook generation (FR-007).

    Tracks relationship to source suggestion, traces, and patterns
    for full audit trail and reproducibility.
    """

    suggestion_id: str
    canonical_trace_id: str
    canonical_pattern_id: str
    trace_ids: List[str]
    pattern_ids: List[str]


class RunbookDraftGeneratorMeta(BaseModel):
    """Audit trail for generation reproducibility (FR-008)."""

    model: str
    temperature: float
    prompt_hash: str
    response_sha256: str
    run_id: str


class RunbookDraft(BaseModel):
    """Generated operational runbook with SRE-standard format.

    Contains structured fields for programmatic access and
    full Markdown content for human consumption.
    """

    runbook_id: str
    title: str
    rationale: str  # Plain-language reasoning citing source trace
    markdown_content: str  # Full Markdown (GitHub/Confluence ready)

    # Structured fields for programmatic access
    symptoms: List[str]
    diagnosis_commands: List[str]  # Minimum 2 required
    mitigation_steps: List[str]
    escalation_criteria: str

    # Lineage (FR-007)
    source: RunbookDraftSource

    # Lifecycle
    status: RunbookDraftStatus
    edit_source: EditSource
    generated_at: datetime
    updated_at: datetime
    generator_meta: RunbookDraftGeneratorMeta


class ApprovalMetadata(BaseModel):
    actor: str
    action: str
    timestamp: datetime
    notes: Optional[str] = None


class RunbookArtifactResponse(BaseModel):
    suggestion_id: str
    suggestion_status: SuggestionStatus
    approval_metadata: Optional[ApprovalMetadata] = None
    runbook: RunbookDraft


def get_runbook_draft_response_schema() -> Dict[str, Any]:
    """Return JSON schema for Gemini response_schema enforcing RunbookDraft shape.

    The schema requires:
    - title: Runbook title
    - rationale: Plain-language reasoning citing source trace (Demo-Ready Transparency)
    - markdown_content: Full Markdown with 6 SRE sections
    - symptoms: Array of observable indicators (min 1)
    - diagnosis_commands: Array of specific commands/queries (min 2 per FR-006)
    - mitigation_steps: Array of immediate actions
    - escalation_criteria: When/who/threshold for escalation
    - status: draft or needs_human_input
    """
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "markdown_content": {"type": "string"},
            "symptoms": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "diagnosis_commands": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            "mitigation_steps": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "escalation_criteria": {"type": "string"},
            "status": {"type": "string", "enum": [e.value for e in RunbookDraftStatus]},
        },
        "required": [
            "title",
            "rationale",
            "markdown_content",
            "symptoms",
            "diagnosis_commands",
            "mitigation_steps",
            "escalation_criteria",
            "status",
        ],
    }


class RunbookErrorType(str, Enum):
    """Types of runbook generation errors (FR-008)."""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    VERTEX_ERROR = "vertex_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class RunbookError(BaseModel):
    """Per-suggestion error record for diagnostic storage (FR-008)."""

    model_config = {"protected_namespaces": ()}

    run_id: str
    suggestion_id: str
    error_type: RunbookErrorType
    error_message: str
    recorded_at: datetime
    model_response_sha256: Optional[str] = None
    model_response_excerpt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "run_id": self.run_id,
            "suggestion_id": self.suggestion_id,
            "error_type": self.error_type.value,
            "error_message": self.error_message,
            "recorded_at": self.recorded_at.isoformat(),
        }
        if self.model_response_sha256:
            result["model_response_sha256"] = self.model_response_sha256
        if self.model_response_excerpt:
            result["model_response_excerpt"] = self.model_response_excerpt
        return result


class RunbookDraftGeneratedFields(BaseModel):
    """Subset returned from Gemini (validated before composing RunbookDraft)."""

    title: str
    rationale: str
    markdown_content: str
    symptoms: List[str]
    diagnosis_commands: List[str]
    mitigation_steps: List[str]
    escalation_criteria: str
    status: RunbookDraftStatus
