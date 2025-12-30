"""Pydantic models for eval test generator.

These models align with:
- specs/004-eval-test-case-generator/data-model.md
- specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml
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


class EvalDraftStatus(str, Enum):
    """Eval test draft readiness status."""

    DRAFT = "draft"
    NEEDS_HUMAN_INPUT = "needs_human_input"


class EditSource(str, Enum):
    """Source of the current draft content."""

    GENERATED = "generated"
    HUMAN = "human"


class EvalTestRunRequest(BaseModel):
    """Request body for POST /eval-tests/run-once."""

    batch_size: Optional[int] = Field(None, alias="batchSize", ge=1, le=200)
    dry_run: Optional[bool] = Field(None, alias="dryRun")
    suggestion_ids: Optional[List[str]] = Field(None, alias="suggestionIds")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class EvalTestGenerateRequest(BaseModel):
    """Request body for POST /eval-tests/generate/{suggestionId}."""

    dry_run: Optional[bool] = Field(None, alias="dryRun")
    force_overwrite: Optional[bool] = Field(None, alias="forceOverwrite")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class EvalTestOutcomeStatus(str, Enum):
    """Per-suggestion outcome status in a batch run."""

    GENERATED = "generated"
    SKIPPED = "skipped"
    ERROR = "error"


class EvalTestOutcome(BaseModel):
    suggestion_id: str = Field(..., alias="suggestionId")
    status: EvalTestOutcomeStatus
    error_reason: Optional[str] = Field(None, alias="errorReason")

    model_config = {"populate_by_name": True}


class EvalTestRunSummary(BaseModel):
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
    suggestion_outcomes: Optional[List[EvalTestOutcome]] = Field(None, alias="suggestionOutcomes")

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


class EvalTestGenerateResponse(BaseModel):
    suggestion_id: str = Field(..., alias="suggestionId")
    status: str
    eval_test: Optional[Dict[str, Any]] = Field(None, alias="evalTest")

    model_config = {"populate_by_name": True}


class EvalTestDraftSource(BaseModel):
    suggestion_id: str
    canonical_trace_id: str
    canonical_pattern_id: str
    trace_ids: List[str]
    pattern_ids: List[str]


class EvalTestDraftInput(BaseModel):
    prompt: str
    required_state: Optional[str] = None
    tools_involved: List[str] = Field(default_factory=list)


class EvalTestDraftAssertions(BaseModel):
    required: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    golden_output: Optional[str] = None
    notes: Optional[str] = None


class EvalTestDraftGeneratorMeta(BaseModel):
    model: str
    temperature: float
    prompt_hash: str
    response_sha256: str
    run_id: str


class EvalTestDraft(BaseModel):
    eval_test_id: str
    title: str
    rationale: str
    source: EvalTestDraftSource
    input: EvalTestDraftInput
    assertions: EvalTestDraftAssertions
    status: EvalDraftStatus
    edit_source: EditSource
    generated_at: datetime
    updated_at: datetime
    generator_meta: EvalTestDraftGeneratorMeta


class ApprovalMetadata(BaseModel):
    actor: str
    action: str
    timestamp: datetime
    notes: Optional[str] = None


class EvalTestArtifactResponse(BaseModel):
    suggestion_id: str
    suggestion_status: SuggestionStatus
    approval_metadata: Optional[ApprovalMetadata] = None
    eval_test: EvalTestDraft


def get_eval_test_draft_response_schema() -> Dict[str, Any]:
    """Return JSON schema for Gemini response_schema enforcing EvalTestDraft shape."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "input": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "required_state": {"type": "string"},
                    "tools_involved": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt", "tools_involved"],
            },
            "assertions": {
                "type": "object",
                "properties": {
                    "required": {"type": "array", "items": {"type": "string"}},
                    "forbidden": {"type": "array", "items": {"type": "string"}},
                    "golden_output": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["required", "forbidden"],
            },
            "status": {"type": "string", "enum": [e.value for e in EvalDraftStatus]},
        },
        "required": ["title", "rationale", "input", "assertions", "status"],
    }


class EvalTestErrorType(str, Enum):
    """Types of eval test generation errors."""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    VERTEX_ERROR = "vertex_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class EvalTestError(BaseModel):
    """Per-suggestion error record for diagnostic storage."""

    model_config = {"protected_namespaces": ()}

    run_id: str
    suggestion_id: str
    error_type: EvalTestErrorType
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


class EvalTestDraftGeneratedFields(BaseModel):
    """Subset returned from Gemini (validated before composing EvalTestDraft)."""

    title: str
    rationale: str
    input: EvalTestDraftInput
    assertions: EvalTestDraftAssertions
    status: EvalDraftStatus
