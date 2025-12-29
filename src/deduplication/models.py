"""Pydantic models for deduplication service request/response and Suggestion schema.

These models align with:
- specs/003-suggestion-deduplication/data-model.md
- specs/003-suggestion-deduplication/contracts/deduplication-openapi.yaml

Reuses FailureType and Severity enums from extraction module for consistency.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# Reuse enums from extraction module for consistency
from src.extraction.models import FailureType, Severity


# ============================================================================
# Enums (matching OpenAPI schema)
# ============================================================================


class SuggestionType(str, Enum):
    """Type of suggestion to generate from failure pattern."""

    EVAL = "eval"
    GUARDRAIL = "guardrail"
    RUNBOOK = "runbook"


class SuggestionStatus(str, Enum):
    """Status of a suggestion in the approval workflow.

    State transitions:
    - pending -> approved (terminal)
    - pending -> rejected (terminal)
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PatternOutcomeStatus(str, Enum):
    """Per-pattern processing outcome status."""

    CREATED_NEW = "created_new"
    MERGED = "merged"
    ERROR = "error"


class TriggeredBy(str, Enum):
    """How the deduplication run was initiated."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


# ============================================================================
# Embedded Models (per data-model.md)
# ============================================================================


class SourceTraceEntry(BaseModel):
    """Reference to a contributing trace in a suggestion's lineage.

    Embedded in: Suggestion.source_traces
    """

    trace_id: str = Field(..., description="Reference to original Datadog trace.")
    pattern_id: str = Field(..., description="Reference to extracted FailurePattern.")
    added_at: datetime = Field(..., description="When this trace was merged in.")
    similarity_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity score when merged (null for first trace).",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {
            "trace_id": self.trace_id,
            "pattern_id": self.pattern_id,
            "added_at": self.added_at.isoformat(),
        }
        if self.similarity_score is not None:
            result["similarity_score"] = self.similarity_score
        return result


class PatternSummary(BaseModel):
    """Consolidated pattern information for a suggestion.

    Embedded in: Suggestion.pattern
    """

    failure_type: FailureType = Field(..., description="From FailureType enum.")
    trigger_condition: str = Field(..., description="Primary trigger description.")
    title: str = Field(..., description="Concise pattern title.")
    summary: str = Field(..., description="1-2 sentence description.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        return {
            "failure_type": self.failure_type.value,
            "trigger_condition": self.trigger_condition,
            "title": self.title,
            "summary": self.summary,
        }


class SuggestionContent(BaseModel):
    """Generated artifacts for a suggestion (populated by downstream services).

    Embedded in: Suggestion.suggestion_content
    """

    eval_test: Optional[Dict[str, Any]] = Field(
        None, description="Generated eval test case (Issue #4)."
    )
    guardrail_rule: Optional[Dict[str, Any]] = Field(
        None, description="Generated guardrail config (Issue #5)."
    )
    runbook_snippet: Optional[Dict[str, Any]] = Field(
        None, description="Generated runbook content (Issue #6)."
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {}
        if self.eval_test:
            result["eval_test"] = self.eval_test
        if self.guardrail_rule:
            result["guardrail_rule"] = self.guardrail_rule
        if self.runbook_snippet:
            result["runbook_snippet"] = self.runbook_snippet
        return result


class ApprovalMetadata(BaseModel):
    """Approval/rejection metadata for a suggestion.

    Embedded in: Suggestion.approval_metadata
    """

    actor: str = Field(..., description="Who approved/rejected (email or API key ID).")
    action: str = Field(..., description="One of: approved, rejected.")
    notes: Optional[str] = Field(None, description="Optional reviewer notes.")
    timestamp: datetime = Field(..., description="When action was taken.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {
            "actor": self.actor,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.notes:
            result["notes"] = self.notes
        return result


class StatusHistoryEntry(BaseModel):
    """A record of a status transition in a suggestion's audit trail.

    Embedded in: Suggestion.version_history
    """

    previous_status: Optional[SuggestionStatus] = Field(
        None, description="Previous status (null for creation)."
    )
    new_status: SuggestionStatus = Field(..., description="New status after transition.")
    actor: str = Field(..., description="Who made the change.")
    timestamp: datetime = Field(..., description="When change occurred.")
    notes: Optional[str] = Field(None, description="Optional notes/reason.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {
            "new_status": self.new_status.value,
            "actor": self.actor,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.previous_status:
            result["previous_status"] = self.previous_status.value
        if self.notes:
            result["notes"] = self.notes
        return result


# ============================================================================
# Core Entity: Suggestion
# ============================================================================


class Suggestion(BaseModel):
    """A deduplicated recommendation derived from one or more failure patterns.

    Collection: evalforge_suggestions
    Document ID: suggestion_id (format: sugg_{uuid})

    Validation Rules:
    - suggestion_id must be unique
    - source_traces must have at least one entry
    - embedding must have exactly 768 elements
    - status can only transition: pending -> approved OR pending -> rejected
    - version_history must have at least one entry (initial creation)
    """

    suggestion_id: str = Field(
        ..., description="Unique identifier (format: sugg_{uuid})."
    )
    type: SuggestionType = Field(
        ..., description="One of: eval, guardrail, runbook."
    )
    status: SuggestionStatus = Field(
        ..., description="One of: pending, approved, rejected."
    )
    severity: Severity = Field(
        ..., description="One of: low, medium, high, critical."
    )
    source_traces: List[SourceTraceEntry] = Field(
        ...,
        min_length=1,
        description="Contributing trace IDs with timestamps.",
    )
    pattern: PatternSummary = Field(..., description="Consolidated pattern info.")
    embedding: List[float] = Field(
        ...,
        min_length=768,
        max_length=768,
        description="768-dimensional embedding vector.",
    )
    similarity_group: str = Field(
        ..., description="Group ID for merged patterns."
    )
    suggestion_content: Optional[SuggestionContent] = Field(
        None, description="Generated artifacts (populated by future issues)."
    )
    approval_metadata: Optional[ApprovalMetadata] = Field(
        None, description="Set when approved/rejected."
    )
    version_history: List[StatusHistoryEntry] = Field(
        ...,
        min_length=1,
        description="Audit trail of status changes.",
    )
    created_at: datetime = Field(..., description="First creation timestamp (UTC).")
    updated_at: datetime = Field(..., description="Last modification timestamp (UTC).")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict."""
        result = {
            "suggestion_id": self.suggestion_id,
            "type": self.type.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "source_traces": [st.to_dict() for st in self.source_traces],
            "pattern": self.pattern.to_dict(),
            "embedding": self.embedding,
            "similarity_group": self.similarity_group,
            "version_history": [vh.to_dict() for vh in self.version_history],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if self.suggestion_content:
            result["suggestion_content"] = self.suggestion_content.to_dict()
        if self.approval_metadata:
            result["approval_metadata"] = self.approval_metadata.to_dict()
        return result


# ============================================================================
# Request Models
# ============================================================================


class DeduplicationRunRequest(BaseModel):
    """Request body for POST /dedup/run-once."""

    batch_size: Optional[int] = Field(
        None,
        alias="batchSize",
        ge=1,
        le=50,
        description="Maximum patterns to process in this run.",
    )
    dry_run: Optional[bool] = Field(
        None,
        alias="dryRun",
        description="If true, compute similarity but don't persist changes.",
    )
    triggered_by: Optional[TriggeredBy] = Field(
        None,
        alias="triggeredBy",
        description="Indicates whether the run was scheduled or manually triggered.",
    )

    model_config = {"populate_by_name": True}


class StatusUpdateRequest(BaseModel):
    """Request body for PATCH /suggestions/{suggestionId}/status (T032 - US3).

    Status transitions allowed per FR-011:
    - pending -> approved
    - pending -> rejected

    Terminal states (approved, rejected) cannot be changed.
    """

    status: SuggestionStatus = Field(
        ...,
        description="New status: 'approved' or 'rejected'.",
    )
    actor: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Who is making the change (email or API key ID).",
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional notes explaining the approval/rejection.",
    )


class StatusUpdateResponse(BaseModel):
    """Response for PATCH /suggestions/{suggestionId}/status."""

    suggestion_id: str = Field(..., alias="suggestionId")
    previous_status: str = Field(..., alias="previousStatus")
    new_status: str = Field(..., alias="newStatus")
    actor: str
    timestamp: datetime
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}


# ============================================================================
# Response Models
# ============================================================================


class PatternOutcome(BaseModel):
    """Per-pattern outcome in a deduplication run summary."""

    pattern_id: str = Field(..., alias="patternId")
    status: PatternOutcomeStatus
    suggestion_id: Optional[str] = Field(None, alias="suggestionId")
    similarity_score: Optional[float] = Field(None, alias="similarityScore")
    error_reason: Optional[str] = Field(None, alias="errorReason")

    model_config = {"populate_by_name": True}


class DeduplicationRunSummary(BaseModel):
    """Per-run summary for POST /dedup/run-once response."""

    run_id: str = Field(..., alias="runId", description="Unique identifier for this run.")
    started_at: datetime = Field(..., alias="startedAt", description="Run start timestamp (UTC).")
    finished_at: datetime = Field(..., alias="finishedAt", description="Run completion timestamp (UTC).")
    triggered_by: TriggeredBy = Field(..., alias="triggeredBy", description="How the run was initiated.")
    patterns_processed: int = Field(
        ..., alias="patternsProcessed", description="Number of patterns fetched and processed."
    )
    suggestions_created: int = Field(
        ..., alias="suggestionsCreated", description="New suggestions created."
    )
    suggestions_merged: int = Field(
        ..., alias="suggestionsMerged", description="Patterns merged into existing suggestions."
    )
    embedding_errors: Optional[int] = Field(
        None, alias="embeddingErrors", description="Patterns that failed embedding generation."
    )
    average_similarity_score: Optional[float] = Field(
        None, alias="averageSimilarityScore", description="Average similarity score for merged patterns."
    )
    processing_duration_ms: int = Field(
        ..., alias="processingDurationMs", description="Total processing time in milliseconds."
    )
    pattern_outcomes: Optional[List[PatternOutcome]] = Field(
        None, alias="patternOutcomes", description="Per-pattern outcome details."
    )

    model_config = {"populate_by_name": True}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict for run record persistence."""
        result = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "triggered_by": self.triggered_by.value,
            "patterns_processed": self.patterns_processed,
            "suggestions_created": self.suggestions_created,
            "suggestions_merged": self.suggestions_merged,
            "processing_duration_ms": self.processing_duration_ms,
        }
        if self.embedding_errors is not None:
            result["embedding_errors"] = self.embedding_errors
        if self.average_similarity_score is not None:
            result["average_similarity_score"] = self.average_similarity_score
        if self.pattern_outcomes:
            result["pattern_outcomes"] = [
                {
                    "pattern_id": o.pattern_id,
                    "status": o.status.value,
                    "suggestion_id": o.suggestion_id,
                    "similarity_score": o.similarity_score,
                    "error_reason": o.error_reason,
                }
                for o in self.pattern_outcomes
            ]
        return result


# ============================================================================
# Health Check Response
# ============================================================================


class HealthResponse(BaseModel):
    """Response for GET /health endpoint."""

    status: str = Field(..., description="Service health status.")
    version: str = Field(..., description="Service version.")
    embedding_service: Optional[str] = Field(
        None, description="Embedding service availability."
    )


# ============================================================================
# Error Response
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: str = Field(..., description="Error type/code.")
    message: str = Field(..., description="Human-readable error message.")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details.")


# ============================================================================
# API Response Models (for US2 lineage and US4 dashboard)
# ============================================================================


class SourceTraceResponse(BaseModel):
    """API response format for source trace entry (camelCase)."""

    trace_id: str = Field(..., alias="traceId")
    pattern_id: str = Field(..., alias="patternId")
    added_at: datetime = Field(..., alias="addedAt")
    similarity_score: Optional[float] = Field(None, alias="similarityScore")

    model_config = {"populate_by_name": True}


class PatternSummaryResponse(BaseModel):
    """API response format for pattern summary (camelCase)."""

    failure_type: str = Field(..., alias="failureType")
    trigger_condition: str = Field(..., alias="triggerCondition")
    title: str
    summary: str

    model_config = {"populate_by_name": True}


class StatusHistoryResponse(BaseModel):
    """API response format for status history entry (camelCase)."""

    previous_status: Optional[str] = Field(None, alias="previousStatus")
    new_status: str = Field(..., alias="newStatus")
    actor: str
    timestamp: datetime
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}


class SuggestionResponse(BaseModel):
    """API response format for a suggestion (camelCase, per OpenAPI contract)."""

    suggestion_id: str = Field(..., alias="suggestionId")
    type: str
    status: str
    severity: str
    source_traces: List[SourceTraceResponse] = Field(..., alias="sourceTraces")
    pattern: PatternSummaryResponse
    similarity_group: Optional[str] = Field(None, alias="similarityGroup")
    version_history: List[StatusHistoryResponse] = Field(..., alias="versionHistory")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_suggestion(cls, suggestion: "Suggestion") -> "SuggestionResponse":
        """Convert internal Suggestion model to API response format."""
        return cls(
            suggestion_id=suggestion.suggestion_id,
            type=suggestion.type.value,
            status=suggestion.status.value,
            severity=suggestion.severity.value,
            source_traces=[
                SourceTraceResponse(
                    trace_id=st.trace_id,
                    pattern_id=st.pattern_id,
                    added_at=st.added_at,
                    similarity_score=st.similarity_score,
                )
                for st in suggestion.source_traces
            ],
            pattern=PatternSummaryResponse(
                failure_type=suggestion.pattern.failure_type.value,
                trigger_condition=suggestion.pattern.trigger_condition,
                title=suggestion.pattern.title,
                summary=suggestion.pattern.summary,
            ),
            similarity_group=suggestion.similarity_group,
            version_history=[
                StatusHistoryResponse(
                    previous_status=vh.previous_status.value if vh.previous_status else None,
                    new_status=vh.new_status.value,
                    actor=vh.actor,
                    timestamp=vh.timestamp,
                    notes=vh.notes,
                )
                for vh in suggestion.version_history
            ],
            created_at=suggestion.created_at,
            updated_at=suggestion.updated_at,
        )


class SuggestionListResponse(BaseModel):
    """API response for list of suggestions with pagination."""

    suggestions: List[SuggestionResponse]
    total: int
    next_cursor: Optional[str] = Field(None, alias="nextCursor")

    model_config = {"populate_by_name": True}
