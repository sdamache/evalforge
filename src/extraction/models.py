"""Pydantic models for extraction service request/response and FailurePattern schema.

These models align with:
- specs/002-extract-failure-patterns/data-model.md
- specs/002-extract-failure-patterns/contracts/extraction-openapi.yaml
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Enums (matching OpenAPI schema)
# ============================================================================


class FailureType(str, Enum):
    """Standardized failure type categories from controlled vocabulary."""

    HALLUCINATION = "hallucination"
    TOXICITY = "toxicity"
    WRONG_TOOL = "wrong_tool"
    RUNAWAY_LOOP = "runaway_loop"
    PII_LEAK = "pii_leak"
    STALE_DATA = "stale_data"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    CLIENT_ERROR = "client_error"


class Severity(str, Enum):
    """Severity levels for failure patterns."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggeredBy(str, Enum):
    """How the extraction run was initiated."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


class TraceOutcomeStatus(str, Enum):
    """Per-trace processing outcome status."""

    STORED = "stored"
    SKIPPED = "skipped"
    VALIDATION_FAILED = "validation_failed"
    ERROR = "error"
    TIMED_OUT = "timed_out"


class ExtractionErrorType(str, Enum):
    """Types of extraction errors."""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    VERTEX_ERROR = "vertex_error"
    TIMEOUT = "timeout"
    OVERSIZE = "oversize"
    UNKNOWN = "unknown"


# ============================================================================
# Request Models
# ============================================================================


class ExtractionRunRequest(BaseModel):
    """Request body for POST /extraction/run-once."""

    batch_size: Optional[int] = Field(
        None,
        alias="batchSize",
        ge=1,
        le=500,
        description="Maximum number of unprocessed traces to process in this run.",
    )
    dry_run: Optional[bool] = Field(
        None,
        alias="dryRun",
        description="If true, performs extraction without writing patterns or updating processed flags.",
    )
    trace_ids: Optional[List[str]] = Field(
        None,
        alias="traceIds",
        description="Optional explicit list of trace IDs to process (overrides unprocessed query).",
    )
    triggered_by: Optional[TriggeredBy] = Field(
        None,
        alias="triggeredBy",
        description="Indicates whether the run was scheduled or manually triggered.",
    )

    model_config = {"populate_by_name": True}


# ============================================================================
# FailurePattern Schema (core output model)
# ============================================================================


class Evidence(BaseModel):
    """Supporting evidence from the trace."""

    signals: List[str] = Field(
        ...,
        min_length=1,
        description="At least one trace-derived signal (e.g., error codes, latency spikes).",
    )
    excerpt: Optional[str] = Field(
        None,
        description="Short redacted text excerpt (optional and never full transcripts).",
    )


class ReproductionContext(BaseModel):
    """Context needed to reproduce the failure."""

    input_pattern: str = Field(
        ...,
        description="Typical input phrasing/shape that reproduces the issue.",
    )
    required_state: Optional[str] = Field(
        None,
        description="Preconditions needed to reproduce (optional).",
    )
    tools_involved: List[str] = Field(
        default_factory=list,
        description="Tool names involved in the failure.",
    )


class FailurePattern(BaseModel):
    """Structured failure pattern extracted from a single trace.

    Fields align with spec FR-003 and FR-010.
    This is the core schema for patterns stored in evalforge_failure_patterns collection.
    """

    pattern_id: str = Field(
        ...,
        description="Stable identifier for the pattern (format: pattern_{source_trace_id}).",
    )
    source_trace_id: str = Field(
        ...,
        description="References the source FailureCapture.trace_id (FR-003 trace reference).",
    )
    title: str = Field(
        ...,
        description="Concise pattern title describing the failure (FR-003 pattern title).",
    )
    failure_type: FailureType = Field(
        ...,
        description="Standardized category from controlled vocabulary (FR-003).",
    )
    trigger_condition: str = Field(
        ...,
        description="Short label describing what triggered the failure (FR-003 primary contributing factor).",
    )
    summary: str = Field(
        ...,
        description="1-2 sentence description of what happened (FR-003 concise summary).",
    )
    root_cause_hypothesis: str = Field(
        ...,
        description="Best explanation for why the failure occurred (FR-003 root-cause hypothesis).",
    )
    evidence: Evidence = Field(
        ...,
        description="Supporting evidence from the trace (FR-003).",
    )
    recommended_actions: List[str] = Field(
        ...,
        min_length=1,
        description="At least one prevention/mitigation action (FR-003).",
    )
    reproduction_context: ReproductionContext = Field(
        ...,
        description="Context for reproducing the failure.",
    )
    severity: Severity = Field(
        ...,
        description="Severity level of the failure.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (FR-003, FR-009).",
    )
    confidence_rationale: str = Field(
        ...,
        description="Short explanation of key signals that influenced confidence (FR-010).",
    )
    extracted_at: datetime = Field(
        ...,
        description="Extraction timestamp in UTC (FR-003).",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        return {
            "pattern_id": self.pattern_id,
            "source_trace_id": self.source_trace_id,
            "title": self.title,
            "failure_type": self.failure_type.value,
            "trigger_condition": self.trigger_condition,
            "summary": self.summary,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "evidence": {
                "signals": self.evidence.signals,
                "excerpt": self.evidence.excerpt,
            },
            "recommended_actions": self.recommended_actions,
            "reproduction_context": {
                "input_pattern": self.reproduction_context.input_pattern,
                "required_state": self.reproduction_context.required_state,
                "tools_involved": self.reproduction_context.tools_involved,
            },
            "severity": self.severity.value,
            "confidence": self.confidence,
            "confidence_rationale": self.confidence_rationale,
            "extracted_at": self.extracted_at.isoformat(),
        }


# ============================================================================
# Response Models
# ============================================================================


class TraceOutcome(BaseModel):
    """Per-trace outcome in a run summary."""

    source_trace_id: str = Field(..., alias="sourceTraceId")
    status: TraceOutcomeStatus
    pattern_id: Optional[str] = Field(None, alias="patternId")
    error_reason: Optional[str] = Field(None, alias="errorReason")

    model_config = {"populate_by_name": True}


class ExtractionRunSummary(BaseModel):
    """Per-run summary matching FR-007 requirements for audit/debugging."""

    run_id: str = Field(..., alias="runId", description="Unique identifier for this extraction run.")
    started_at: datetime = Field(..., alias="startedAt", description="Run start timestamp (UTC).")
    finished_at: datetime = Field(..., alias="finishedAt", description="Run completion timestamp (UTC).")
    triggered_by: TriggeredBy = Field(..., alias="triggeredBy", description="How the run was initiated.")
    batch_size: int = Field(..., alias="batchSize", description="Maximum traces configured for this run.")
    picked_up_count: int = Field(
        ..., alias="pickedUpCount", description="Total traces fetched for attempted processing (FR-007)."
    )
    stored_count: int = Field(..., alias="storedCount", description="Patterns successfully stored (FR-007).")
    validation_failed_count: int = Field(
        ..., alias="validationFailedCount", description="Patterns that failed schema validation (FR-007)."
    )
    error_count: int = Field(
        ..., alias="errorCount", description="Processing errors excluding timeouts (FR-007)."
    )
    timed_out_count: int = Field(
        ..., alias="timedOutCount", description="Traces that exceeded time budget (FR-007)."
    )
    trace_outcomes: Optional[List[TraceOutcome]] = Field(
        None, alias="traceOutcomes", description="Per-trace summaries with references (FR-007)."
    )

    model_config = {"populate_by_name": True}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict for run record persistence."""
        result = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "triggered_by": self.triggered_by.value,
            "batch_size": self.batch_size,
            "picked_up_count": self.picked_up_count,
            "stored_count": self.stored_count,
            "validation_failed_count": self.validation_failed_count,
            "error_count": self.error_count,
            "timed_out_count": self.timed_out_count,
        }
        if self.trace_outcomes:
            result["trace_outcomes"] = [
                {
                    "source_trace_id": o.source_trace_id,
                    "status": o.status.value,
                    "pattern_id": o.pattern_id,
                    "error_reason": o.error_reason,
                }
                for o in self.trace_outcomes
            ]
        return result


# ============================================================================
# Error Record Model
# ============================================================================


class ExtractionError(BaseModel):
    """Per-trace extraction error record for diagnostic storage."""

    run_id: str = Field(..., description="Run ID when error occurred.")
    source_trace_id: str = Field(..., description="Trace ID that caused the error.")
    error_type: ExtractionErrorType = Field(..., description="Classification of the error.")
    error_message: str = Field(..., description="Human-readable error description.")
    model_response_sha256: Optional[str] = Field(
        None, description="Hash of the full model response for correlation."
    )
    model_response_excerpt: Optional[str] = Field(
        None, description="Short redacted excerpt of model response."
    )
    recorded_at: datetime = Field(..., description="When the error was recorded.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {
            "run_id": self.run_id,
            "source_trace_id": self.source_trace_id,
            "error_type": self.error_type.value,
            "error_message": self.error_message,
            "recorded_at": self.recorded_at.isoformat(),
        }
        if self.model_response_sha256:
            result["model_response_sha256"] = self.model_response_sha256
        if self.model_response_excerpt:
            result["model_response_excerpt"] = self.model_response_excerpt
        return result


# ============================================================================
# Gemini Response Schema (for structured output)
# ============================================================================


def get_failure_pattern_response_schema() -> Dict[str, Any]:
    """Return the JSON schema dict for Gemini response_schema parameter.

    This schema is used with google-genai SDK's response_mime_type="application/json"
    to guarantee structured JSON output from Gemini.
    """
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "failure_type": {
                "type": "string",
                "enum": [e.value for e in FailureType],
            },
            "trigger_condition": {"type": "string"},
            "summary": {"type": "string"},
            "root_cause_hypothesis": {"type": "string"},
            "evidence": {
                "type": "object",
                "properties": {
                    "signals": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "excerpt": {"type": "string"},
                },
                "required": ["signals"],
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reproduction_context": {
                "type": "object",
                "properties": {
                    "input_pattern": {"type": "string"},
                    "required_state": {"type": "string"},
                    "tools_involved": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["input_pattern", "tools_involved"],
            },
            "severity": {
                "type": "string",
                "enum": [e.value for e in Severity],
            },
            "confidence": {"type": "number"},
            "confidence_rationale": {"type": "string"},
        },
        "required": [
            "title",
            "failure_type",
            "trigger_condition",
            "summary",
            "root_cause_hypothesis",
            "evidence",
            "recommended_actions",
            "reproduction_context",
            "severity",
            "confidence",
            "confidence_rationale",
        ],
    }
